"""Indexing and searching the corpus (ARG-053).

Idempotent by fragment hash: re-indexing the same document does not duplicate a row, does not
change the order and does not move a single vector. That matters more than it sounds — the corpus
is re-indexed on every content update, and an index that drifts makes yesterday's citation point
somewhere else today.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from argos_ai.rag.chunking import Chunk, chunk_legal_text
from argos_ai.rag.embeddings import Embedder

ORIGINS = ("norm", "guide", "client")
DEFAULT_K = 12
_INSERT = (
    "INSERT INTO argos.rag_chunks (source, origin, reference, text, embedding, chunk_sha256) "
    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (chunk_sha256) DO NOTHING"
)
_SEARCH = (
    "SELECT reference, text, origin, source, 1 - (embedding <=> %(vector)s::vector) "
    "FROM argos.rag_chunks "
    "WHERE (%(origins)s::text[] IS NULL OR origin = ANY(%(origins)s::text[])) "
    "ORDER BY embedding <=> %(vector)s::vector LIMIT %(k)s"
)
_LEXICAL = (
    "SELECT reference, text, origin, source, "
    "ts_rank(to_tsvector('spanish', reference || ' ' || text), plainto_tsquery('spanish', %(q)s)) "
    "FROM argos.rag_chunks "
    "WHERE (%(origins)s::text[] IS NULL OR origin = ANY(%(origins)s::text[])) "
    "AND to_tsvector('spanish', reference || ' ' || text) "
    "@@ plainto_tsquery('spanish', %(q)s) "
    "ORDER BY 5 DESC LIMIT %(k)s"
)


@dataclass(frozen=True, slots=True)
class Hit:
    reference: str
    text: str
    origin: str
    source: str
    score: float


def _vector(values: Sequence[float]) -> str:
    """pgvector reads a vector as its literal text; psycopg does not know the type."""
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def index_chunks(
    dsn: str, source: str, origin: str, chunks: Sequence[Chunk], embedder: Embedder
) -> int:
    """Store the fragments that are not there yet. Returns how many were new."""
    if origin not in ORIGINS:
        raise ValueError(f"unknown origin: {origin!r}")
    if not chunks:
        return 0
    vectors = embedder.embed([chunk.text for chunk in chunks])
    rows = [
        (source, origin, chunk.reference, chunk.text, _vector(vector), chunk.sha256)
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany(_INSERT, rows)
        written = cur.rowcount
    return max(written, 0)


def index_document(
    dsn: str, source: str, origin: str, text: str, norm: str, embedder: Embedder
) -> int:
    """Cut a legal text by its structure and index it."""
    return index_chunks(dsn, source, origin, chunk_legal_text(text, norm), embedder)


def search(
    dsn: str,
    query: str,
    embedder: Embedder,
    origins: Sequence[str] | None = None,
    k: int = DEFAULT_K,
) -> list[Hit]:
    """The closest fragments by cosine distance."""
    [vector] = embedder.embed([query])
    arguments: dict[str, Any] = {
        "vector": _vector(vector),
        "origins": list(origins) if origins else None,
        "k": k,
    }
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_SEARCH, arguments).fetchall()
    return [Hit(str(r[0]), str(r[1]), str(r[2]), str(r[3]), float(r[4])) for r in rows]


def search_lexical(
    dsn: str, query: str, origins: Sequence[str] | None = None, k: int = DEFAULT_K
) -> list[Hit]:
    """The lexical half of the hybrid retrieval of ARG-054.

    It lives here because it reads the same table. Article numbers are what an embedding treats
    worst, and «32.1.a» is exactly what a DPO types.
    """
    arguments: dict[str, Any] = {
        "q": query,
        "origins": list(origins) if origins else None,
        "k": k,
    }
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(_LEXICAL, arguments).fetchall()
    return [Hit(str(r[0]), str(r[1]), str(r[2]), str(r[3]), float(r[4])) for r in rows]
