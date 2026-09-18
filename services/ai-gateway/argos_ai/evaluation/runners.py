"""The four trades run against their golden sets (ARG-059).

Each runner feeds a trade the input of every case, lets it do its work —retrieve, validate, verify,
calibrate— and compares what comes out with what the case expects. The model's answer comes from a
`make_backend(case)` the caller chooses:

- **oracle**: a backend that answers each case with its expected output. It does not measure the
  model; it measures everything else — whether retrieval reaches the fragment the answer cites,
  whether the checks accept what is right and reject the traps, whether the scores and the gate
  work. If the oracle does not reach a threshold, the pipeline itself is losing points. This is
  what runs in `make check`, without weights and without a GPU (ADR-0009).
- **real**: the served model. Its score is the model's quality, and it gates a release.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

import yaml

from argos_ai.backends.base import Backend
from argos_ai.backends.fake import FakeBackend
from argos_ai.classify.calibration import Calibrator
from argos_ai.classify.service import SemanticClassifier
from argos_ai.evaluation.goldens import EDITORIAL_DIR, Case
from argos_ai.evaluation.metrics import Outcome
from argos_ai.gateway import Gateway, GatewayError
from argos_ai.generate.challenge_gen import propose_challenge
from argos_ai.guardrails import OutputRejectedError
from argos_ai.rag.chunking import Chunk
from argos_ai.rag.embeddings import Embedder
from argos_ai.rag.indexer import index_chunks
from argos_ai.rag.pipeline import CitationError, answer
from argos_ai.reports.writer import SUMMARY_SCHEMA, DraftRejectedError, check_summary
from argos_challenges.dsl import LintContext, parse_challenge
from argos_challenges.library.translation import read_challenge, to_internal
from argos_inventory.classify.assisted import ColumnContext
from argos_ontology.vocabulary import LIBRARY_DIR

BackendFor = Callable[[Case], Backend]
QUOTAS = {service: 10**9 for service in ("assistant", "inventory", "challenge", "reports")}


def _gateway(backend: Backend) -> Gateway:
    return Gateway(backend, journal=lambda _: None, usage=lambda _: None, quotas=QUOTAS)


def _obligations() -> dict[str, dict[str, Any]]:
    return {
        str(document["id"]): document
        for document in (
            yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted(EDITORIAL_DIR.glob("OBL-*.yaml"))
        )
    }


def index_corpus(dsn: str, embedder: Embedder) -> int:
    """The v1 populations as a citable corpus: one fragment per obligation, cited by its article."""
    chunks = [
        Chunk(
            reference=f"{document['norma']} art. {document['articulo']}",
            heading=str(document["titulo"]),
            body=str(document["texto_resumen"]),
        )
        for document in _obligations().values()
    ]
    return index_chunks(dsn, "poblaciones v1", "norm", chunks, embedder)


# ---------- what the oracle answers ----------


def oracle_answer(suite: str, case: Case) -> str:
    """The expected output of a case, in the shape the trade asks the model for."""
    expected = case.expected
    if suite == "rag":
        citations = [
            {"n": number, "reference": reference}
            for number, reference in enumerate(expected.get("citations", []), start=1)
        ]
        return json.dumps(
            {
                "answer": "Respuesta de referencia.",
                "sufficient": expected["sufficient"],
                "citations": citations,
            }
        )
    if suite == "classify":
        category = expected.get("category")
        items = (
            [] if category is None else [{"key": case.id, "category": category, "confidence": 0.9}]
        )
        return json.dumps({"items": items})
    if suite == "generate":
        family = str(expected["challenge_id"]).split("-", 1)[0]
        path = LIBRARY_DIR / "challenges" / family / f"{expected['challenge_id']}.yaml"
        return json.dumps({"yaml": path.read_text(encoding="utf-8")})
    if suite == "reports":
        section = {"title": "Resumen", "body": case.input["draft"]}
        return json.dumps({"sections": [section], "verdict_ids": []})
    raise ValueError(f"unknown suite: {suite!r}")


def oracle_backends(suite: str) -> BackendFor:
    return lambda case: FakeBackend.of([oracle_answer(suite, case)])


# ---------- the runners ----------


async def run_rag(
    cases: list[Case], backend_for: BackendFor, dsn: str, embedder: Embedder
) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for case in cases:
        expected = case.expected
        try:
            result = await answer(
                dsn, case.input["question"], _gateway(backend_for(case)), embedder, ["norm"]
            )
        except (CitationError, GatewayError) as exc:
            outcomes.append(Outcome(case.id, case.kind, False, str(exc)))
            continue
        if expected["sufficient"]:
            correct = result.sufficient and set(expected["citations"]) <= set(result.citations)
        else:
            correct = not result.sufficient and not result.citations
        outcomes.append(Outcome(case.id, case.kind, correct, str(result.citations)))
    return outcomes


async def run_classify(cases: list[Case], backend_for: BackendFor) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for case in cases:
        table, _, name = str(case.input["column"]).rpartition(".")
        column = ColumnContext(case.id, name, "text", table, ())
        classifier = SemanticClassifier(_gateway(backend_for(case)), Calibrator({}))
        proposals = await classifier.propose_async([column])
        expected = case.expected.get("category")
        got = proposals[0].category if proposals else None
        outcomes.append(Outcome(case.id, case.kind, got == expected, f"{got}"))
    return outcomes


async def run_generate(cases: list[Case], backend_for: BackendFor) -> list[Outcome]:
    context = LintContext.from_library()
    obligations = _obligations()
    outcomes: list[Outcome] = []
    for case in cases:
        obligation = str(case.input["obligation"])
        text = str(obligations[obligation]["texto_resumen"])
        proposal = await propose_challenge(obligation, text, _gateway(backend_for(case)), context)
        if not proposal.valid:
            outcomes.append(Outcome(case.id, case.kind, False, "; ".join(proposal.warnings)))
            continue
        spec = parse_challenge(to_internal(read_challenge(proposal.yaml)))
        expected = case.expected
        correct = (
            spec.id == expected["challenge_id"]
            and spec.probe_kind == expected["probe_kind"]
            and spec.asset_class == expected["asset_class"]
            and spec.obligation == obligation
        )
        outcomes.append(Outcome(case.id, case.kind, correct, spec.id))
    return outcomes


async def run_reports(cases: list[Case], backend_for: BackendFor) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for case in cases:
        figures: Mapping[str, object] = case.input["figures"]
        gateway = _gateway(backend_for(case))
        try:
            reply = await gateway.chat_json(
                "reports", "Redacta.", json.dumps(figures), SUMMARY_SCHEMA
            )
            check_summary(reply.data["sections"], figures, reply.data["verdict_ids"], [])
            accepted, detail = True, "aceptado"
        except (DraftRejectedError, OutputRejectedError) as exc:
            accepted, detail = False, str(exc)
        outcomes.append(Outcome(case.id, case.kind, accepted == case.expected["accepted"], detail))
    return outcomes
