"""Capacity benchmark · the smoke profile end to end and the throw-away database of the tool."""

import importlib.util
import json
from pathlib import Path

import psycopg
import pytest

from argos_common.config import get_config
from argos_inventory.benchmark import PROFILES, run_benchmark
from argos_inventory.graph.store import GraphStore

from .conftest import ADMIN_DSN
from .sources import ROOT

pytestmark = pytest.mark.integration

_spec = importlib.util.spec_from_file_location(
    "inventory_benchmark", ROOT / "tools" / "inventory_benchmark.py"
)
assert _spec is not None and _spec.loader is not None
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def test_smoke_profile_measures_the_whole_pipeline(migrated_db: str) -> None:
    report = run_benchmark(migrated_db, PROFILES["smoke"])
    assert (report["tables"], report["columns"]) == (100, 600)
    assert report["pass1"]["deltas"] == {"appeared": 0, "disappeared": 0, "anomalous_growth": 0}
    # one table per system retired and one added, each with 6 columns: 4 x (1 + 6)
    assert report["pass2"]["deltas"] == {"appeared": 28, "disappeared": 28, "anomalous_growth": 0}
    # 4 systems + 4 schemas + 4 x 26 tables + 4 x 26 x 6 columns + 9 categories
    assert report["graph_nodes"] == 745
    assert report["snapshot"]["nodes"] > 0
    assert report["selector_ms"]["pages"] >= 1
    assert report["selector_ms"]["p95"] >= report["selector_ms"]["p50"] > 0
    assert report["extrapolated_hours"]["full_scan"] > 0
    assert report["extrapolated_hours"]["rescan"] > 0
    [classified] = GraphStore(migrated_db).query(
        "MATCH (:Column)-[r:CLASSIFIED_AS]->(:Category) RETURN count(r)", columns=("n",)
    )
    assert classified["n"] > 0


def test_the_tool_uses_a_throw_away_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARGOS_DATABASE_URL", ADMIN_DSN)
    get_config.cache_clear()
    output = tmp_path / "benchmark.json"
    try:
        assert tool.main(["--profile", "smoke", "--output", str(output)]) == 0
    finally:
        get_config.cache_clear()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["profile"]["name"] == "smoke"
    assert report["database"] is None
    with psycopg.connect(ADMIN_DSN) as conn:
        leftovers = conn.execute(
            "SELECT count(*) FROM pg_database WHERE datname LIKE 'argos\\_bench\\_%'"
        ).fetchone()
    assert leftovers == (0,)
