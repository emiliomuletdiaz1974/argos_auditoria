"""ARG-054 · the whole pipeline: retrieve, cite what was retrieved, or refuse (F06-07)."""

import asyncio
import json
from typing import Any

import pytest
from argos_ai.backends.fake import FakeBackend
from argos_ai.quotas import postgres_gateway
from argos_ai.rag.embeddings import HashEmbedder
from argos_ai.rag.indexer import index_document
from argos_ai.rag.pipeline import CitationError, answer, retrieve

pytestmark = pytest.mark.integration

EMBEDDER = HashEmbedder()
RGPD = """Artículo 32. Seguridad del tratamiento
1. El responsable aplicará medidas técnicas apropiadas, entre otras:
a) la seudonimización y el cifrado de los datos personales;
b) la capacidad de garantizar la confidencialidad permanente de los sistemas.

Artículo 33. Notificación de una violación de la seguridad
1. El responsable la notificará a la autoridad de control a más tardar 72 horas después.
"""


def _corpus(dsn: str) -> None:
    index_document(dsn, "RGPD consolidado", "norm", RGPD, "RGPD", EMBEDDER)


def _answer(dsn: str, replies: list[str], question: str) -> Any:
    gateway = postgres_gateway(dsn, FakeBackend.of(replies))
    return asyncio.run(answer(dsn, question, gateway, EMBEDDER))


def test_an_answer_that_cites_a_retrieved_fragment_is_given(migrated_db: str) -> None:
    _corpus(migrated_db)
    reply = json.dumps(
        {
            "answer": "Hay que notificar a la autoridad en 72 horas.",
            "sufficient": True,
            "citations": [{"n": 1, "reference": "RGPD art. 33.1"}],
        }
    )
    result = _answer(migrated_db, [reply], "¿en cuántas horas se notifica una brecha?")
    assert result.sufficient and result.citations == ["RGPD art. 33.1"]


def test_an_invented_citation_invalidates_the_answer(migrated_db: str) -> None:
    """Better no answer than one that quotes an article that was never retrieved."""
    _corpus(migrated_db)
    reply = json.dumps(
        {
            "answer": "El RGPD lo exige.",
            "sufficient": True,
            "citations": [{"n": 1, "reference": "RGPD art. 99.9"}],
        }
    )
    with pytest.raises(CitationError):
        _answer(migrated_db, [reply], "¿qué exige el RGPD?")


def test_a_question_the_corpus_does_not_cover_is_refused(migrated_db: str) -> None:
    _corpus(migrated_db)
    reply = json.dumps({"answer": "", "sufficient": False, "citations": []})
    result = _answer(migrated_db, [reply], "¿cuál es la sanción máxima de la NIS2?")
    assert result.sufficient is False
    assert result.citations == []
    assert result.nearest, "the refusal shows the nearest fragments so a human can judge"


def test_an_empty_corpus_is_refused_without_calling_the_model(migrated_db: str) -> None:
    backend = FakeBackend.of([])
    gateway = postgres_gateway(migrated_db, backend)
    result = asyncio.run(answer(migrated_db, "¿qué exige el RGPD?", gateway, EMBEDDER))
    assert result.sufficient is False and backend.calls == 0


def test_the_retrieval_puts_the_article_number_in_reach(migrated_db: str) -> None:
    """The lexical half is there for this: an embedding alone loses the number."""
    _corpus(migrated_db)
    references = [hit.reference for hit in retrieve(migrated_db, "33.1", EMBEDDER)]
    assert "RGPD art. 33.1" in references


def test_the_question_is_answered_with_the_fragments_that_were_sent(migrated_db: str) -> None:
    _corpus(migrated_db)
    backend = FakeBackend.of(
        [
            json.dumps(
                {
                    "answer": "Sí.",
                    "sufficient": True,
                    "citations": [{"n": 1, "reference": "RGPD art. 32.1.a"}],
                }
            )
        ]
    )
    gateway = postgres_gateway(migrated_db, backend)
    asyncio.run(answer(migrated_db, "¿hay que cifrar?", gateway, EMBEDDER))
    assert "[1] RGPD art." in backend.last_user
    assert "Pregunta: ¿hay que cifrar?" in backend.last_user
