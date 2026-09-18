"""ARG-057 · the drafter against a real campaign: store only what holds, marked (F06-10)."""

import asyncio
import json
from typing import Any

import psycopg
import pytest
from argos_ai.backends.fake import FakeBackend
from argos_ai.quotas import postgres_gateway
from argos_ai.reports.writer import (
    DraftRejectedError,
    draft_finding_narrative,
    draft_summary,
)

from argos_challenges.evaluator import evaluate
from argos_challenges.findings import open_or_recur
from argos_challenges.store import create_campaign, persist_verdict, pin_campaign

from .sources import register_catalog_system

pytestmark = pytest.mark.integration


def _campaign(dsn: str) -> dict[str, Any]:
    """One campaign with one compliant verdict and one non-compliant verdict and its finding."""
    system_id = register_catalog_system(dsn, "dev-source-postgres")
    campaign_id = create_campaign(dsn, "Campaña para el dictamen", {}, "user:campaign-manager")
    pin_campaign(
        dsn,
        campaign_id,
        snapshot_id=None,
        snapshot_hash=None,
        ontology_version="1.0.0",
        library_version="1.0.0",
        library_sha256="b" * 64,
        applicability_run=None,
    )
    verdicts: list[str] = []
    finding_id = ""
    for name, value in (("ok", "on"), ("ko", "off")):
        unit = {
            "unit_id": f"{name:x<64}"[:64],
            "campaign_id": campaign_id,
            "challenge_id": f"sec-{name}",
            "challenge_version": "1.0",
            "obligation": "OBL-RGPD-32-3",
            "system_id": system_id,
            "node_key": f"k-{name}",
            "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
            "sampling": None,
            "severity": "high",
        }
        verdict = evaluate(unit, {"ok": True, "data": {"rows": [{"ssl": value}]}})
        verdict_id, _ = persist_verdict(dsn, campaign_id, unit, verdict)
        verdicts.append(verdict_id)
        if verdict.result == "non_compliant":
            finding_id = open_or_recur(dsn, campaign_id, unit, verdict, verdict_id)["id"]
    return {"campaign_id": campaign_id, "verdicts": verdicts, "finding_id": finding_id}


def _gateway(dsn: str, reply: dict[str, Any]) -> Any:
    return postgres_gateway(dsn, FakeBackend.of([json.dumps(reply)]))


def _texts(dsn: str) -> list[tuple[str, bool, str]]:
    with psycopg.connect(dsn) as conn:
        return [
            (str(r[0]), bool(r[1]), str(r[2]))
            for r in conn.execute("SELECT kind, generated, prompt_sha256 FROM argos.report_texts")
        ]


def test_a_summary_that_holds_is_stored_marked_as_generated(migrated_db: str) -> None:
    data = _campaign(migrated_db)
    reply = {
        "sections": [
            {"title": "Resumen", "body": "Se ejecutaron 2 unidades y se abrió 1 hallazgo."}
        ],
        "verdict_ids": data["verdicts"],
    }
    asyncio.run(draft_summary(migrated_db, data["campaign_id"], _gateway(migrated_db, reply)))
    [(kind, generated, digest)] = _texts(migrated_db)
    assert kind == "summary" and generated is True and len(digest) == 64


def test_a_summary_with_an_invented_figure_stores_nothing(migrated_db: str) -> None:
    data = _campaign(migrated_db)
    reply = {
        "sections": [{"title": "Resumen", "body": "Se abrieron 7 hallazgos, un 12 % más."}],
        "verdict_ids": [],
    }
    with pytest.raises(DraftRejectedError):
        asyncio.run(draft_summary(migrated_db, data["campaign_id"], _gateway(migrated_db, reply)))
    assert _texts(migrated_db) == []


def test_the_narrative_of_a_finding_is_stored_with_its_verdict(migrated_db: str) -> None:
    data = _campaign(migrated_db)
    reply = {
        "context": "El sistema no es conforme con el artículo 32: ssl está desactivado.",
        "impact": "Las conexiones viajan sin cifrar.",
        "recommendation": "Activar ssl en el servidor.",
        "verdict_id": data["verdicts"][1],
    }
    asyncio.run(
        draft_finding_narrative(migrated_db, data["finding_id"], _gateway(migrated_db, reply))
    )
    assert [kind for kind, _, _ in _texts(migrated_db)] == ["finding"]


def test_a_narrative_that_argues_with_its_verdict_stores_nothing(migrated_db: str) -> None:
    data = _campaign(migrated_db)
    reply = {
        "context": "En la práctica el sistema es conforme.",
        "impact": "Ninguno.",
        "recommendation": "Ninguna.",
        "verdict_id": data["verdicts"][1],
    }
    with pytest.raises(DraftRejectedError):
        asyncio.run(
            draft_finding_narrative(migrated_db, data["finding_id"], _gateway(migrated_db, reply))
        )
    assert _texts(migrated_db) == []


def test_a_stored_text_is_never_edited(migrated_db: str) -> None:
    """A generated text is part of the record: a new draft is a new row, never an edit."""
    data = _campaign(migrated_db)
    reply = {"sections": [{"title": "Resumen", "body": "Sin cifras."}], "verdict_ids": []}
    asyncio.run(draft_summary(migrated_db, data["campaign_id"], _gateway(migrated_db, reply)))
    with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE argos.report_texts SET body = '{}'::jsonb")
