"""Embeddings: the real model, and a deterministic one so the tests need no weights (ARG-053).

Multilingual, because the norm lives in Spanish and in English (ADR-0009). The model is
configuration: nothing above this module names one.
"""

import hashlib
import math
from typing import Protocol

import httpx

DIMENSIONS = 384
TIMEOUT_SECONDS = 60.0


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class HashEmbedder:
    """A stable vector per text, with no model behind it.

    It is not a pretend model —it understands nothing— but it is deterministic and it keeps the
    same text pointing at the same place, which is what the index, the idempotence and the CI
    need. Semantic quality is measured against the real model, in the golden sets.
    """

    def __init__(self, dimensions: int = DIMENSIONS) -> None:
        self._dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            raw = [
                (digest[index % len(digest)] ^ (index * 31 % 256)) / 255.0 - 0.5
                for index in range(self._dimensions)
            ]
            vectors.append(_normalise(raw))
        return vectors


class ServedEmbedder:
    """The embedding model served beside the gateway, through the OpenAI-compatible API."""

    def __init__(self, base_url: str, model: str, client: httpx.Client | None = None) -> None:
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._model = model
        self._client = client

    def embed(self, texts: list[str]) -> list[list[float]]:
        owned = self._client is None
        client = self._client or httpx.Client(timeout=TIMEOUT_SECONDS)
        try:
            response = client.post(self._url, json={"model": self._model, "input": texts})
            response.raise_for_status()
            body = response.json()
        finally:
            if owned:
                client.close()
        return [[float(value) for value in row["embedding"]] for row in body["data"]]
