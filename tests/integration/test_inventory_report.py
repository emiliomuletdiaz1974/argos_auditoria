"""ARG-026 · readable inventory report built from catalog and graph metadata only."""

import asyncio
import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from argos_common.config import get_config
from argos_inventory.catalog.report import render_inventory_report
from argos_inventory.catalog.treatments import import_treatments
from argos_inventory.catalog.views import refresh_catalog
from argos_inventory.graph.model import ai_system_key, column_key, system_key
from argos_inventory.graph.store import GraphStore
from argos_inventory.ingest.handlers import Ingestor

from .inventory_helpers import RecordingBus
from .sources import register_catalog_system

pytestmark = pytest.mark.integration

AT = "2026-09-15T10:00:00+00:00"
DPO = "user:0192b000-0000-7000-8000-00000000d0c0"
GENERATED = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
HEALTH_EDGE = (
    "MATCH (c:Column {key: $key}), (k:Category {name: 'special_category.health'}) "
    "MERGE (c)-[r:CLASSIFIED_AS]->(k) SET r.method = 'dict' SET r.confidence = 0.6"
)
EXTERNAL_FLOW = (
    "MATCH (a:System {key: $source}) MERGE (b:System {key: $target}) SET b.external = true "
    "MERGE (a)-[f:FLOWS_TO]->(b) SET f.method = 'engine_catalog' SET f.confidence = 0.95 "
    "SET f.confirmed = false SET f.evidence = 'billing_link'"
)
AI_CANDIDATE = (
    "MATCH (s:System {key: $system}) MERGE (a:AISystem {key: $key}) "
    "SET a.name = 'table:readmission_risk' SET a.confidence = 0.3 SET a.status = 'pending' "
    "SET a.signals = ['score_column|0.3|readmission_risk'] "
    "MERGE (s)-[:USES_MODEL]->(a)"
)
REVIEW_ROW = (
    "INSERT INTO argos.review_queue (node_key, system_id, qualified_name, proposed_category, "
    "confidence, reason, prompt_hash, proposed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
)
CSV = (
    b"id;name;legal_basis;retention;systems\n"
    b"T-001;Synthetic clinical record;GDPR 9.2.h;15 years;dev-source-postgres\n"
)
HEADINGS = (
    "# Informe de inventario",
    "## Resumen",
    "## Sistemas",
    "## Datos de categorías especiales",
    "## Flujos entre sistemas",
    "## Sistemas de IA candidatos",
    "## Cola de revisión",
    "## Tratamientos declarados",
    "## Advertencias",
)


def _setup(dsn: str) -> tuple[str, str, GraphStore]:
    postgres = register_catalog_system(dsn, "dev-source-postgres")
    files = register_catalog_system(dsn, "dev-files-local")
    store = GraphStore(dsn)
    table: dict[str, Any] = {
        "system_id": postgres,
        "run_id": "run-1",
        "source_connector": "argos_sql.postgres:PostgresConnector",
        "probe_id": "p",
        "journal_seq": 1,
        "observed_at": AT,
        "schema": "clinic",
        "table": "patient_documents",
        "est_rows": 1000,
        "bytes": 8192,
        "comment": None,
        "columns": [
            {"name": c, "type": "text", "nullable": False} for c in ("diagnosis_code", "email")
        ],
    }
    ingestor = Ingestor(store, dsn, RecordingBus())
    asyncio.run(ingestor.handle(table, {"type": "eu.argos.discovery.table_found.v1"}))
    diagnosis = column_key(postgres, "clinic", "patient_documents", "diagnosis_code")
    store.execute(HEALTH_EDGE, {"key": diagnosis})
    store.execute(
        EXTERNAL_FLOW, {"source": system_key(postgres), "target": "external-billing-link"}
    )
    candidate = ai_system_key(postgres, "table:readmission_risk")
    store.execute(AI_CANDIDATE, {"system": system_key(postgres), "key": candidate})
    import_treatments(store, dsn, CSV, DPO)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE argos.systems SET owner = 'dpo.synthetic@example.invalid' WHERE id = %s",
            (postgres,),
        )
        finished = GENERATED - timedelta(hours=3)
        conn.execute(
            "INSERT INTO argos.scan_runs (id, system_id, status, started_at, finished_at) "
            "VALUES (%s, %s, 'completed', %s, %s)",
            (str(uuid.uuid4()), postgres, finished - timedelta(minutes=5), finished),
        )
        conn.execute(
            REVIEW_ROW,
            (
                column_key(postgres, "clinic", "patient_documents", "email"),
                postgres,
                "clinic.patient_documents.email",
                "contact_data",
                0.7,
                "synthetic",
                "0" * 16,
                GENERATED,
            ),
        )
    refresh_catalog(dsn)
    return postgres, files, store


def test_report_contains_every_section_from_metadata(migrated_db: str) -> None:
    _setup(migrated_db)
    report = render_inventory_report(GraphStore(migrated_db), migrated_db, generated_at=GENERATED)
    for heading in HEADINGS:
        assert heading in report, heading
    assert "2026-09-15T12:00:00+00:00" in report
    special_row = (
        "| dev-source-postgres | clinic.patient_documents.diagnosis_code "
        "| special_category.health | dict | 0.60 |"
    )
    assert special_row in report
    assert "engine_catalog" in report and "inferido" in report
    assert "table:readmission_risk" in report and "pendiente" in report
    assert "score_column" in report
    treatment_row = (
        "| T-001 | Synthetic clinical record | GDPR 9.2.h | 15 years | dev-source-postgres |"
    )
    assert treatment_row in report
    assert "| dev-source-postgres | 1 |" in report  # pending reviews per system


def test_report_warns_about_gaps(migrated_db: str) -> None:
    _setup(migrated_db)
    report = render_inventory_report(GraphStore(migrated_db), migrated_db, generated_at=GENERATED)
    warnings = report.split("## Advertencias", 1)[1]
    assert "dev-files-local" in warnings  # no owner and never scanned
    assert "sin responsable" in warnings and "sin exploración" in warnings
    assert "1 flujo(s) inferido(s) sin confirmar" in warnings
    assert "1 columna(s) pendientes de revisión" in warnings


def test_tool_writes_the_report(
    migrated_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(migrated_db)
    monkeypatch.setenv("ARGOS_DATABASE_URL", migrated_db)
    get_config.cache_clear()
    root = Path(__file__).parents[2]
    spec = importlib.util.spec_from_file_location(
        "inventory_report", root / "tools" / "inventory_report.py"
    )
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    output = tmp_path / "inventory.md"
    try:
        assert tool.main(["--output", str(output)]) == 0
    finally:
        get_config.cache_clear()
    assert output.read_text(encoding="utf-8").startswith("# Informe de inventario")
