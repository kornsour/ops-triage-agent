"""Cosine-similarity vector store with on-disk persistence.

Backed by a single numpy matrix; swap for pgvector / FAISS in production without
changing the retriever interface. Vectors are L2-normalized at write time, so a
dot product is the cosine similarity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


class VectorStore:
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._vectors: np.ndarray = np.zeros((0, dim), dtype=np.float32)
        self._meta: list[dict[str, Any]] = []

    def __len__(self) -> int:
        return len(self._meta)

    def add(self, vectors: np.ndarray, metadatas: list[dict[str, Any]]) -> None:
        if vectors.shape[0] != len(metadatas):
            raise ValueError("vectors and metadatas length mismatch")
        if vectors.shape[0] == 0:
            return
        self._vectors = np.vstack([self._vectors, vectors.astype(np.float32)])
        self._meta.extend(metadatas)

    def search(self, query: np.ndarray, k: int = 3) -> list[tuple[float, dict[str, Any]]]:
        if len(self) == 0:
            return []
        sims = self._vectors @ query
        k = min(k, len(self))
        top = np.argsort(-sims)[:k]
        return [(float(sims[i]), self._meta[i]) for i in top]

    def save(self, index_dir: Path) -> None:
        index_dir = Path(index_dir)
        index_dir.mkdir(parents=True, exist_ok=True)
        np.save(index_dir / "vectors.npy", self._vectors)
        (index_dir / "meta.json").write_text(
            json.dumps({"dim": self.dim, "meta": self._meta}, indent=2)
        )

    @classmethod
    def load(cls, index_dir: Path) -> VectorStore:
        index_dir = Path(index_dir)
        meta = json.loads((index_dir / "meta.json").read_text())
        store = cls(dim=meta["dim"])
        store._vectors = np.load(index_dir / "vectors.npy")
        store._meta = meta["meta"]
        return store

    @staticmethod
    def exists(index_dir: Path) -> bool:
        index_dir = Path(index_dir)
        return (index_dir / "vectors.npy").exists() and (index_dir / "meta.json").exists()
