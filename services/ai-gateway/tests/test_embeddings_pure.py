"""ARG-053 · the deterministic embedder carries signal, not noise (F06-12).

It stands in for the embedding model in the CI. If its vectors were noise, the vector half of the
hybrid retrieval would push a right lexical answer out of the context, and the golden sets would be
measuring the noise instead of the pipeline — which is exactly what happened the first time.
"""

import math

from argos_ai.rag.embeddings import DIMENSIONS, HashEmbedder


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


EMBEDDER = HashEmbedder()


CORPUS = [
    "Cifrado en reposo de categorías especiales verificado en el almacén.",
    "Notificación de la violación de seguridad a la autoridad en 72 horas.",
    "Supervisión humana encomendada a personas competentes del sistema de inteligencia artificial.",
    "Plazos de supresión declarados en el registro de actividades de tratamiento.",
    "Acceso inmediato del paciente a sus datos de salud electrónicos.",
    "Base jurídica del tratamiento de categorías especiales de datos.",
]
QUESTIONS = {
    "¿Qué exige el RGPD sobre el cifrado en reposo?": 0,
    "¿En cuántas horas se notifica una violación de seguridad?": 1,
    "¿Quién supervisa un sistema de inteligencia artificial?": 2,
    "¿Se declaran los plazos de supresión en el registro?": 3,
    "¿Tiene el paciente acceso inmediato a su salud electrónica?": 4,
}


def test_each_question_finds_its_own_fragment_first() -> None:
    """Ranking, not a margin: a noise embedder puts the right fragment first one time in six.

    Getting all five right by chance is about one in 7776, so this cannot pass on noise the way
    the first version of this embedder passed a weaker test.
    """
    vectors = EMBEDDER.embed(CORPUS)
    for question, expected in QUESTIONS.items():
        [q] = EMBEDDER.embed([question])
        nearest = max(range(len(CORPUS)), key=lambda index: _cosine(q, vectors[index]))
        assert nearest == expected, question


def test_accents_and_case_do_not_separate_the_same_word() -> None:
    first, second = EMBEDDER.embed(["Violación de la seguridad", "VIOLACION DE LA SEGURIDAD"])
    assert _cosine(first, second) > 0.99


def test_the_same_text_always_gives_the_same_unit_vector() -> None:
    first, second = EMBEDDER.embed(["cifrado en tránsito", "cifrado en tránsito"])
    assert first == second
    assert len(first) == DIMENSIONS
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0)


def test_a_text_without_words_still_gets_a_valid_vector() -> None:
    """pgvector cannot measure a cosine distance against a zero vector."""
    [vector] = EMBEDDER.embed(["¿?"])
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0)
