"""Embeddings: the real model, and a deterministic one so the tests need no weights (ARG-053).

Multilingual, because the norm lives in Spanish and in English (ADR-0009). The model is
configuration: nothing above this module names one.
"""

import hashlib
import math
import re
import unicodedata
from typing import Protocol

import httpx

DIMENSIONS = 384
TIMEOUT_SECONDS = 60.0


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


# Words that say nothing about what a fragment is about.
_STOPWORDS = frozenset(
    [
        "que",
        "los",
        "las",
        "del",
        "por",
        "con",
        "para",
        "una",
        "unos",
        "unas",
        "sus",
        "sobre",
        "como",
        "mas",
        "pero",
        "sin",
        "este",
        "esta",
        "estos",
        "estas",
        "ese",
        "esa",
        "hay",
        "hace",
        "tiene",
        "son",
        "ser",
        "the",
        "and",
        "for",
        "with",
    ]
)
_STEM = 6  # a crude stemmer: «cifrado», «cifrar» and «cifrados» share their first letters


def _words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return [
        word[:_STEM]
        for word in re.findall(r"[a-z0-9]+", plain)
        if len(word) >= 3 and word not in _STOPWORDS
    ]


class HashEmbedder:
    """A bag of words hashed into a fixed number of dimensions, with no model behind it.

    It stands in for the embedding model wherever there are no weights: the tests and the CI. It
    understands no meaning, but texts that share words land near each other, so the vector half of
    the hybrid retrieval carries real signal instead of noise. The first version hashed the whole
    text and gave pure noise; the golden sets caught it, because noise in the vector ranking pushed
    a right lexical answer out of the context. Semantic quality is still measured against the real
    model, as a release gate.
    """

    def __init__(self, dimensions: int = DIMENSIONS) -> None:
        self._dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            raw = [0.0] * self._dimensions
            # A text without words still needs a valid vector: pgvector cannot measure a cosine
            # distance against a zero one.
            for word in _words(text) or ["\x00"]:
                digest = hashlib.sha256(word.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self._dimensions
                raw[index] += 1.0 if digest[4] % 2 == 0 else -1.0
            if not any(raw):
                raw[0] = 1.0
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
