"""Query-time retrieval and context formatting.

Returns scored hits and renders a citation-tagged context block (``[kb-id] ...``)
so downstream grounding checks can verify the draft reply actually cites
retrieved sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from triage.config import Settings, get_settings
from triage.rag.embeddings import Embedder, get_embedder
from triage.rag.store import VectorStore


@dataclass
class Hit:
    doc_id: str
    title: str
    text: str
    score: float
    owner: str
    lineage: dict[str, Any]


class Retriever:
    def __init__(self, store: VectorStore, embedder: Embedder, min_score: float = 0.05) -> None:
        self.store = store
        self.embedder = embedder
        self.min_score = min_score

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> Retriever:
        settings = settings or get_settings()
        embedder = get_embedder(settings)
        if not VectorStore.exists(settings.index_dir):
            raise FileNotFoundError(
                f"No index at {settings.index_dir}. Run: python -m triage.rag.ingest"
            )
        store = VectorStore.load(settings.index_dir)
        return cls(store, embedder)

    def retrieve(self, query: str, k: int = 3) -> list[Hit]:
        qvec = self.embedder.embed(query)
        hits = []
        for score, meta in self.store.search(qvec, k=k):
            if score < self.min_score:
                continue
            hits.append(Hit(
                doc_id=meta["id"], title=meta["title"], text=meta["text"],
                score=round(score, 4), owner=meta["owner"], lineage=meta["lineage"],
            ))
        return hits

    @staticmethod
    def format_context(hits: list[Hit]) -> str:
        if not hits:
            return "(no relevant runbook found)"
        blocks = []
        for h in hits:
            blocks.append(f"[{h.doc_id}] {h.title}\n{h.text}")
        return "\n\n".join(blocks)
