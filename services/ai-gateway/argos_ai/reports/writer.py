"""The drafter of the campaign record: verified figures, untouchable verdicts (ARG-057).

The record needs two texts that today take a consultant hours: the executive summary (what was
verified, what was found, what it means) and the narrative of each finding (context, impact,
recommendation). The model drafts both from structured data under three rules that do not bend:

1. **Every figure of the text is a figure of its data.** The verifier of `figures` checks it; a
   draft with one invented number is not stored at all, not stored with a warning.
2. **The text never alters a verdict.** It narrates compliant or non-compliant; it does not argue.
   A summary may quote verdicts only by the ids of this campaign, and a finding's narrative may not
   claim the compliance its verdict denied.
3. **Every piece is marked** `generated` with the hash of its prompt — the mark the Phase 07 record
   shows the supervisor.

This module reads verdicts and findings; it has no way to write them, by code (the architecture
test) and by privilege (the `argos_ai` role).
"""

import asyncio
import hashlib
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg.types.json import Jsonb

from argos_ai.gateway import Gateway
from argos_ai.reports.figures import unsupported_figures
from argos_common.errors import ArgosError

PROMPT_FILE = Path(__file__).resolve().parents[4] / "library" / "prompts" / "reports.yaml"
SERVICE = "reports"
# What a narrative may not say about a finding that exists because its verdict was non-compliant.
_COMPLIANCE_CLAIMS = re.compile(
    r"(?<!no )\b(es|son|resulta|resultan|considerarse|considera)\s+conformes?\b"
    r"|(?<!no )\bcumple\b|\bno procede\b",
    re.IGNORECASE,
)
SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["sections", "verdict_ids"],
    "additionalProperties": False,
    "properties": {
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["title", "body"],
                "additionalProperties": False,
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
            },
        },
        "verdict_ids": {"type": "array", "items": {"type": "string"}},
    },
}
FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["context", "impact", "recommendation", "verdict_id"],
    "additionalProperties": False,
    "properties": {
        "context": {"type": "string"},
        "impact": {"type": "string"},
        "recommendation": {"type": "string"},
        "verdict_id": {"type": "string"},
    },
}


class DraftRejectedError(ArgosError):
    """The draft broke one of the three rules; nothing of it is stored."""


def _prompts() -> tuple[dict[str, str], str]:
    raw = PROMPT_FILE.read_bytes()
    return dict(yaml.safe_load(raw.decode("utf-8"))), hashlib.sha256(raw).hexdigest()


def _figures(values: Iterable[object]) -> list[object]:
    return [value for value in values if isinstance(value, int | float)]


def check_summary(
    sections: Sequence[Mapping[str, str]],
    figures: Mapping[str, object],
    cited: Sequence[str],
    verdicts: Iterable[str],
) -> None:
    """Rules 1 and 2 for a summary. Raises naming what broke them."""
    text = " ".join(f"{section['title']} {section['body']}" for section in sections)
    offending = unsupported_figures(text, _figures(figures.values()))
    if offending:
        raise DraftRejectedError(f"cifras que no están en los datos: {offending}")
    unknown = sorted(set(cited) - set(verdicts))
    if unknown:
        raise DraftRejectedError(
            f"el resumen cita veredictos que no son de esta campaña: {unknown}"
        )


def check_finding_narrative(narrative: Mapping[str, str], figures: Mapping[str, object]) -> None:
    """Rules 1 and 2 for the narrative of a finding. Raises naming what broke them."""
    text = " ".join(str(narrative[key]) for key in ("context", "impact", "recommendation"))
    if _COMPLIANCE_CLAIMS.search(text):
        raise DraftRejectedError("la narrativa discute el veredicto del que sale el hallazgo")
    offending = unsupported_figures(text, _figures(figures.values()))
    if offending:
        raise DraftRejectedError(f"cifras que no están en los datos: {offending}")


def _campaign_figures(dsn: str, campaign_id: str) -> tuple[dict[str, object], list[str]]:
    with psycopg.connect(dsn) as conn:
        results: dict[str, int] = dict(
            conn.execute(
                "SELECT result, count(*) FROM argos.verdicts WHERE campaign_id = %s GROUP BY 1",
                (campaign_id,),
            ).fetchall()
        )
        severities: dict[str, int] = dict(
            conn.execute(
                "SELECT severity, count(*) FROM argos.findings WHERE campaign_id = %s GROUP BY 1",
                (campaign_id,),
            ).fetchall()
        )
        systems = conn.execute(
            "SELECT count(DISTINCT system_id) FROM argos.verdicts WHERE campaign_id = %s",
            (campaign_id,),
        ).fetchone()
        verdicts = [
            str(row[0])
            for row in conn.execute(
                "SELECT id FROM argos.verdicts WHERE campaign_id = %s", (campaign_id,)
            ).fetchall()
        ]
    figures: dict[str, object] = {
        "units": sum(int(v) for v in results.values()),
        "systems": int(systems[0]) if systems else 0,
        "findings": sum(int(v) for v in severities.values()),
    }
    figures.update({f"result_{key}": int(value) for key, value in results.items()})
    figures.update({f"severity_{key}": int(value) for key, value in severities.items()})
    return figures, verdicts


def _store(
    dsn: str,
    kind: str,
    campaign_id: str,
    finding_id: str | None,
    body: Mapping[str, Any],
    digest: str,
) -> str:
    text_id = str(uuid.uuid4())
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.report_texts (id, kind, campaign_id, finding_id, body, "
            "prompt_sha256) VALUES (%s, %s, %s, %s, %s, %s)",
            (text_id, kind, campaign_id, finding_id, Jsonb(dict(body)), digest),
        )
    return text_id


async def draft_summary(dsn: str, campaign_id: str, gateway: Gateway) -> str:
    """Draft, verify and store the executive summary of a campaign. Returns the text id."""
    prompts, digest = _prompts()
    figures, verdicts = await asyncio.to_thread(_campaign_figures, dsn, campaign_id)
    user = f"Datos de la campaña: {figures}\nIdentificadores de veredicto: {verdicts}"
    answer = await gateway.chat_json(SERVICE, prompts["summary"], user, SUMMARY_SCHEMA)
    sections = answer.data["sections"]
    check_summary(sections, figures, answer.data["verdict_ids"], verdicts)
    return await asyncio.to_thread(_store, dsn, "summary", campaign_id, None, answer.data, digest)


def _finding(dsn: str, finding_id: str) -> dict[str, Any]:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT campaign_id::text, challenge_id, obligation, severity, occurrences, "
            "last_verdict::text, detail FROM argos.findings WHERE id = %s",
            (finding_id,),
        ).fetchone()
    if row is None:
        raise DraftRejectedError(f"no existe el hallazgo {finding_id}")
    keys = (
        "campaign_id",
        "challenge_id",
        "obligation",
        "severity",
        "occurrences",
        "last_verdict",
        "detail",
    )
    return dict(zip(keys, row, strict=True))


async def draft_finding_narrative(dsn: str, finding_id: str, gateway: Gateway) -> str:
    """Draft, verify and store the narrative of one finding. Returns the text id."""
    prompts, digest = _prompts()
    finding = await asyncio.to_thread(_finding, dsn, finding_id)
    figures = {"occurrences": finding["occurrences"]}
    user = (
        f"Hallazgo: reto {finding['challenge_id']}, obligación {finding['obligation']}, "
        f"severidad {finding['severity']}, ocurrencias {finding['occurrences']}.\n"
        f"Veredicto del que sale: {finding['last_verdict']}"
    )
    answer = await gateway.chat_json(SERVICE, prompts["finding"], user, FINDING_SCHEMA)
    if answer.data["verdict_id"] != finding["last_verdict"]:
        raise DraftRejectedError("la narrativa cita un veredicto que no es el de su hallazgo")
    check_finding_narrative(answer.data, figures)
    return await asyncio.to_thread(
        _store, dsn, "finding", finding["campaign_id"], finding_id, answer.data, digest
    )
