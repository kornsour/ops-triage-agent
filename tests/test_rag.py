from triage.rag.embeddings import HashingEmbedder
from triage.rag.ingest import _govern, ingest
from triage.rag.retriever import Retriever


def test_ingest_governs_and_indexes(seeded):
    store, report = ingest(seeded, verbose=False)
    assert report.ingested >= 6
    assert report.rejected == 0
    assert report.ok()
    # lineage is captured for every ingested doc
    for doc in report.docs:
        if doc.status == "ingested":
            assert doc.doc_id and doc.doc_id.startswith("kb-")


def test_governance_rejects_bad_metadata():
    errors, _ = _govern({"id": "bad id", "title": "t"}, "short")
    assert any("convention" in e for e in errors)
    assert any("missing required field" in e for e in errors)
    assert any("too short" in e for e in errors)


def test_retrieval_finds_relevant_runbook(seeded):
    r = Retriever.from_settings(seeded)
    hits = r.retrieve("I am locked out and forgot my password", k=3)
    assert hits
    assert hits[0].doc_id == "kb-password-reset"
    ctx = Retriever.format_context(hits)
    assert "[kb-password-reset]" in ctx


def test_embeddings_are_normalized_and_deterministic():
    e = HashingEmbedder(dim=64)
    v1 = e.embed("password reset lockout")
    v2 = e.embed("password reset lockout")
    assert (v1 == v2).all()
    assert abs(float((v1 * v1).sum()) - 1.0) < 1e-5
