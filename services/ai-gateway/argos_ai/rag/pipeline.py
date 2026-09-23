"""RAG with a citation that has to be real, and an honest refusal (ARG-054).

The demand here is above the usual one: **the exact citation**. An assistant that says «el RGPD
exige X» without the paragraph is noise for a DPO; one that says «art. 32.1.a» and shows the
fragment is a tool.

The pipeline: hybrid retrieval (vector plus lexical, because article numbers are what embeddings
treat worst), reciprocal rank fusion, a short rerank by the model over the candidates, and a
context of numbered fragments that the prompt forces it to cite. Every citation of the answer is
checked against what was actually retrieved: **an invented citation invalidates the answer**, and
an answer with no support is refused out loud —«no encuentro base normativa en el corpus para
afirmarlo» is a correct answer of the product, not a failure.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from argos_ai.gateway import Gateway
from argos_ai.rag.embeddings import Embedder
from argos_ai.rag.fusion import reciprocal_rank_fusion
from argos_ai.rag.indexer import Hit, search, search_lexical
from argos_common.errors import ArgosError

RETRIEVE = 12
CONTEXT_SIZE = 6
SERVICE = "assistant"
REFUSAL_TEXT = (
    "No encuentro base normativa en el corpus cargado para afirmarlo. "
    "Estos son los fragmentos más cercanos por si quieres juzgarlo tú."
)
SYSTEM_PROMPT = (
    "Eres un asistente normativo. Respondes solo con lo que digan los fragmentos numerados que "
    "se te dan. Cada afirmación lleva la cita del fragmento del que sale, por su número. "
    "Si los fragmentos no bastan para responder, devuelves sufficient=false y no citas nada. "
    "No decides si un sistema cumple o no: eso no es tuyo."
)
ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answer", "citations", "sufficient"],
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "sufficient": {"type": "boolean"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["n", "reference"],
                "additionalProperties": False,
                "properties": {
                    "n": {"type": "integer", "minimum": 1},
                    "reference": {"type": "string"},
                },
            },
        },
    },
}


class CitationError(ArgosError):
    """The answer cites something that was not retrieved, or claims support it does not have."""


@dataclass(frozen=True, slots=True)
class Answer:
    answer: str
    citations: list[str]
    sufficient: bool
    nearest: list[str] = field(default_factory=list)


def build_context(fragments: Sequence[tuple[str, str]]) -> str:
    """The numbered fragments, as the model reads them and as the prompt demands they be cited."""
    return "\n\n".join(
        f"[{number}] {reference}\n{text}"
        for number, (reference, text) in enumerate(fragments, start=1)
    )


def checked_citations(citations: Sequence[Mapping[str, Any]], allowed: Sequence[str]) -> list[str]:
    """The citations of the answer, or `CitationError` naming the one that was invented."""
    if not citations:
        raise CitationError("una respuesta con soporte suficiente no puede venir sin citas")
    references = [str(citation["reference"]) for citation in citations]
    invented = [reference for reference in references if reference not in set(allowed)]
    if invented:
        raise CitationError(f"la respuesta cita fragmentos que no se recuperaron: {invented}")
    return references


def refusal(nearest: Sequence[str]) -> Answer:
    """The honest answer when the corpus does not cover the question."""
    return Answer(REFUSAL_TEXT, [], False, list(nearest))


def retrieve(
    dsn: str, question: str, embedder: Embedder, origins: Sequence[str] | None = None
) -> list[Hit]:
    """The hybrid retrieval, fused: what the two searches agree on comes first."""
    vector = search(dsn, question, embedder, origins=origins, k=RETRIEVE)
    lexical = search_lexical(dsn, question, origins=origins, k=RETRIEVE)

    # A fragment is its origin and its reference: a client document that reuses the reference of
    # an article is not that article (security review F09-02, SEC-048).
    def key(hit: Hit) -> str:
        return f"{hit.origin}|{hit.reference}"

    by_key = {key(hit): hit for hit in [*lexical, *vector]}
    order = reciprocal_rank_fusion([[key(hit) for hit in vector], [key(hit) for hit in lexical]])
    return [by_key[item] for item in order]


async def answer(
    dsn: str,
    question: str,
    gateway: Gateway,
    embedder: Embedder,
    origins: Sequence[str] | None = None,
) -> Answer:
    """The answer to a normative question, with its citations checked, or an honest refusal."""
    hits = retrieve(dsn, question, embedder, origins)
    if not hits:
        return refusal([])
    context = hits[:CONTEXT_SIZE]
    user = (
        f"{build_context([(hit.reference, hit.text) for hit in context])}\n\nPregunta: {question}"
    )
    result = await gateway.chat_json(
        SERVICE, SYSTEM_PROMPT, user, ANSWER_SCHEMA, priority="interactive"
    )
    data = result.data
    allowed = [hit.reference for hit in context]
    if not data.get("sufficient"):
        return refusal(allowed)
    return Answer(str(data["answer"]), checked_citations(data["citations"], allowed), True)
