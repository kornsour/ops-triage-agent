"""Retrieval-augmented generation pipeline with ingestion governance.

    embeddings   Deterministic hashing embedder (offline) or OpenAI embeddings.
    store        Cosine-similarity vector store with on-disk persistence.
    ingest       Loads the knowledge base, runs governance checks, builds the index.
    retriever    Query-time retrieval + context formatting with citations.
"""

from .embeddings import get_embedder
from .retriever import Retriever
from .store import VectorStore

__all__ = ["get_embedder", "Retriever", "VectorStore"]
