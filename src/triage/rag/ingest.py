"""Knowledge-base ingestion with data governance.

Governance is a first-class step, not an afterthought — it maps directly to the
Enterprise AI Platform posting's "data governance" requirement:

    schema    Required metadata present and well-formed (id, title, owner, ...).
    quality   Non-empty body, minimum length, recognized id format.
    lineage   Source path, content hash, ingest timestamp, last-reviewed age.

Documents failing a *blocking* check are excluded from the index; quality
warnings (e.g. stale review date) are surfaced but do not block. The report is
printed and returned so it can be asserted on in tests / CI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date
from hashlib import sha256
from pathlib import Path
from typing import Any

from triage.config import Settings, get_settings
from triage.rag.embeddings import get_embedder
from triage.rag.store import VectorStore

REQUIRED_FIELDS = ("id", "title", "owner", "last_reviewed", "tags")
MIN_BODY_CHARS = 80
STALE_AFTER_DAYS = 365
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass
class DocResult:
    source: str
    doc_id: str | None
    status: str  # ingested | rejected
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class GovernanceReport:
    docs: list[DocResult] = field(default_factory=list)

    @property
    def ingested(self) -> int:
        return sum(1 for d in self.docs if d.status == "ingested")

    @property
    def rejected(self) -> int:
        return sum(1 for d in self.docs if d.status == "rejected")

    @property
    def warnings(self) -> int:
        return sum(len(d.warnings) for d in self.docs)

    def ok(self) -> bool:
        return self.rejected == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingested": self.ingested,
            "rejected": self.rejected,
            "warnings": self.warnings,
            "docs": [d.__dict__ for d in self.docs],
        }


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            meta[key.strip()] = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = val
    return meta, m.group(2).strip()


def _govern(meta: dict[str, Any], body: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for fld in REQUIRED_FIELDS:
        if not meta.get(fld):
            errors.append(f"missing required field: {fld}")
    doc_id = str(meta.get("id", ""))
    if doc_id and not re.fullmatch(r"kb-[a-z0-9-]+", doc_id):
        errors.append(f"id {doc_id!r} does not match kb-<slug> convention")
    if len(body) < MIN_BODY_CHARS:
        errors.append(f"body too short ({len(body)} < {MIN_BODY_CHARS} chars)")
    reviewed = str(meta.get("last_reviewed", ""))
    if reviewed:
        try:
            age = (date.today() - date.fromisoformat(reviewed)).days
            if age > STALE_AFTER_DAYS:
                warnings.append(f"runbook last reviewed {age} days ago (stale)")
        except ValueError:
            errors.append(f"last_reviewed {reviewed!r} is not ISO-8601")
    return errors, warnings


def ingest(settings: Settings | None = None, verbose: bool = True) -> tuple[VectorStore, GovernanceReport]:
    settings = settings or get_settings()
    embedder = get_embedder(settings)
    store = VectorStore(dim=embedder.dim)
    report = GovernanceReport()

    texts: list[str] = []
    metas: list[dict[str, Any]] = []

    for path in sorted(Path(settings.knowledge_base_dir).glob("*.md")):
        raw = path.read_text()
        meta, body = _parse_frontmatter(raw)
        errors, warnings = _govern(meta, body)
        if errors:
            report.docs.append(DocResult(path.name, meta.get("id"), "rejected", errors, warnings))
            continue
        from datetime import datetime

        record = {
            "id": meta["id"],
            "title": meta["title"],
            "text": body,
            "tags": meta.get("tags", []),
            "owner": meta["owner"],
            "lineage": {
                "source": str(path.relative_to(settings.knowledge_base_dir.parent)),
                "content_sha256": sha256(raw.encode()).hexdigest(),
                "ingested_at": datetime.now(UTC).isoformat(),
                "last_reviewed": meta.get("last_reviewed"),
            },
        }
        texts.append(f"{meta['title']}\n{body}")
        metas.append(record)
        report.docs.append(DocResult(path.name, meta["id"], "ingested", [], warnings))

    if texts:
        store.add(embedder.embed_batch(texts), metas)
        store.save(settings.index_dir)

    if verbose:
        print(f"RAG ingest: {report.ingested} ingested, {report.rejected} rejected, "
              f"{report.warnings} warnings -> {settings.index_dir}")
        for d in report.docs:
            for e in d.errors:
                print(f"  REJECT {d.source}: {e}")
            for w in d.warnings:
                print(f"  WARN   {d.source}: {w}")
    return store, report


if __name__ == "__main__":
    ingest()
