"""Embeddings.

The default `HashingEmbedder` is deterministic and dependency-light (no model
download), so retrieval works identically offline, in tests, and in CI. It maps
tokens into a fixed-width vector via feature hashing with sublinear term
weighting, then L2-normalizes — so cosine similarity reflects term overlap.

`OpenAIEmbedder` is a drop-in for production-grade semantic retrieval.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

from triage.config import Settings, get_settings

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "is", "it", "for", "on",
         "i", "my", "me", "you", "your", "this", "that", "with", "can", "cant",
         "please", "help", "im", "am", "are", "be", "have", "has", "get", "got"}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 1]


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> np.ndarray: ...

    def embed_batch(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _hash(self, token: str) -> int:
        h = hashlib.md5(token.encode()).hexdigest()  # noqa: S324 - non-crypto use
        return int(h, 16) % self.dim

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        counts: dict[int, int] = {}
        for tok in tokenize(text):
            idx = self._hash(tok)
            counts[idx] = counts.get(idx, 0) + 1
        for idx, c in counts.items():
            vec[idx] = 1.0 + np.log(c)  # sublinear tf
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self.embed(t) for t in texts]) if texts else np.zeros((0, self.dim))


class OpenAIEmbedder:  # pragma: no cover - requires network + key
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model
        self.dim = 1536

    def embed(self, text: str) -> np.ndarray:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        resp = self._client.embeddings.create(model=self.model, input=texts)
        return np.array([d.embedding for d in resp.data], dtype=np.float32)


def get_embedder(settings: Settings | None = None) -> Embedder:
    settings = settings or get_settings()
    if settings.embeddings_provider == "openai":
        return OpenAIEmbedder(api_key=settings.openai_api_key)
    return HashingEmbedder(dim=settings.embeddings_dim)
