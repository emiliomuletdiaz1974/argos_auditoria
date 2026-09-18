"""ARG-053 · the corpus indexed on pgvector: idempotent, citable and searchable (F06-06)."""

import psycopg
import pytest
from argos_ai.rag.chunking import chunk_legal_text
from argos_ai.rag.embeddings import DIMENSIONS, HashEmbedder
from argos_ai.rag.indexer import index_document, search, search_lexical

pytestmark = pytest.mark.integration

EMBEDDER = HashEmbedder()
RGPD = """Artículo 32. Seguridad del tratamiento
1. El responsable aplicará medidas técnicas apropiadas, entre otras:
a) la seudonimización y el cifrado de datos personales;
b) la capacidad de garantizar la confidencialidad permanente de los sistemas.
2. Al evaluar la adecuación del nivel de seguridad se tendrán en cuenta los riesgos.

Artículo 33. Notificación de una violación de la seguridad
1. El responsable la notificará a la autoridad de control a más tardar 72 horas después.
"""
PROCEDURE = """Artículo 1. Procedimiento interno de cifrado
1. Los volúmenes de la sede central se cifran con LUKS2 y la clave se sella en el TPM.
"""


def _index(dsn: str) -> int:
    return index_document(dsn, "RGPD consolidado", "norm", RGPD, "RGPD", EMBEDDER)


def test_a_document_is_indexed_once_and_re_indexing_adds_nothing(migrated_db: str) -> None:
    written = _index(migrated_db)
    assert written == len(chunk_legal_text(RGPD, "RGPD"))
    assert _index(migrated_db) == 0
    with psycopg.connect(migrated_db) as conn:
        assert conn.execute("SELECT count(*) FROM argos.rag_chunks").fetchone() == (written,)


def test_every_indexed_fragment_is_citable(migrated_db: str) -> None:
    _index(migrated_db)
    with psycopg.connect(migrated_db) as conn:
        references = [r[0] for r in conn.execute("SELECT reference FROM argos.rag_chunks")]
    assert "RGPD art. 32.1.a" in references
    assert all(reference.startswith("RGPD art. ") for reference in references)


def test_the_vector_has_the_dimension_of_the_column(migrated_db: str) -> None:
    _index(migrated_db)
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute("SELECT vector_dims(embedding) FROM argos.rag_chunks LIMIT 1").fetchone()
    assert row == (DIMENSIONS,)


def test_the_search_finds_the_fragment_it_was_given(migrated_db: str) -> None:
    _index(migrated_db)
    chunk = next(c for c in chunk_legal_text(RGPD, "RGPD") if c.reference == "RGPD art. 33.1")
    [best, *_] = search(migrated_db, chunk.text, EMBEDDER, k=3)
    assert best.reference == "RGPD art. 33.1"
    assert best.score > 0.99


def test_the_search_can_be_limited_to_an_origin(migrated_db: str) -> None:
    """The assistant must be able to cite the norm without the client's own procedure."""
    _index(migrated_db)
    index_document(migrated_db, "Procedimiento del cliente", "client", PROCEDURE, "PROC", EMBEDDER)
    origins = {hit.origin for hit in search(migrated_db, "cifrado", EMBEDDER, origins=["norm"])}
    assert origins == {"norm"}


def test_the_lexical_search_finds_an_article_number(migrated_db: str) -> None:
    """What an embedding treats worst is exactly what a DPO types."""
    _index(migrated_db)
    hits = search_lexical(migrated_db, "32.1.a", k=5)
    assert "RGPD art. 32.1.a" in [hit.reference for hit in hits]


def test_an_unknown_origin_is_refused(migrated_db: str) -> None:
    with pytest.raises(ValueError, match="origin"):
        index_document(migrated_db, "x", "inventado", RGPD, "RGPD", EMBEDDER)
