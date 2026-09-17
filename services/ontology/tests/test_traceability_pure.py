"""ARG-037 · no obligation without a challenge and no challenge without an obligation."""

import csv
import importlib.util
import io
import json
from pathlib import Path
from typing import Any

import pytest
from rdflib import Graph

from argos_ontology.editorial.compiler import compile_obligation
from argos_ontology.traceability import (
    CATALOG_FILE,
    CSV_COLUMNS,
    build_matrix,
    load_challenge_catalog,
    matrix_csv,
    matrix_json,
    parse_challenge_catalog,
)

ROOT = Path(__file__).resolve().parents[3]
CATALOG = {
    "challenges": [
        {
            "id": "sec-encryption-at-rest",
            "family": "security",
            "evidence_type": "configuration",
            "description": "Cifrado en reposo",
        },
        {
            "id": "ret-table-retention",
            "family": "retention",
            "evidence_type": "query_result",
            "description": "Plazo de conservación en tablas",
        },
    ]
}


def _obligation(identifier: str, extra: str) -> str:
    return (
        f'id: {identifier}\nnorma: RGPD\narticulo: "32"\ntitulo: Obligación {identifier}\n'
        f"vigente_desde: 2018-05-25\nseveridad: high\naplica_a: [AC-stored-health-data]\n{extra}"
    )


def _graph(*templates: str) -> Graph:
    graph = Graph()
    for template in templates:
        graph.parse(data=compile_obligation(template), format="turtle")
    return graph


def test_a_covered_and_a_pending_obligation_make_a_clean_matrix() -> None:
    graph = _graph(
        _obligation("OBL-RGPD-32-1", "verificado_por: [sec-encryption-at-rest]\n"),
        _obligation("OBL-RGPD-5-1", "verificado_por: [ret-table-retention]\n"),
        _obligation("OBL-RGPD-30-1", 'pendiente_verificacion: "Sin sonda posible aún"\n'),
    )
    rows, errors = build_matrix(graph, parse_challenge_catalog(CATALOG))
    assert errors == []
    assert [(r.obligation.rsplit("/", 1)[1], r.status) for r in rows] == [
        ("OBL-RGPD-30-1", "pending"),
        ("OBL-RGPD-32-1", "covered"),
        ("OBL-RGPD-5-1", "covered"),
    ]
    assert rows[1].challenges == ("sec-encryption-at-rest",)
    assert rows[0].pending_reason == "Sin sonda posible aún"


@pytest.mark.parametrize(
    ("templates", "message"),
    [
        ([_obligation("OBL-RGPD-32-1", "")], "without challenge or verificationPending"),
        (
            [_obligation("OBL-RGPD-32-1", "verificado_por: [sec-unknown-probe]\n")],
            "challenge not in catalog: sec-unknown-probe",
        ),
        (
            [
                _obligation(
                    "OBL-RGPD-32-1",
                    "verificado_por: [sec-encryption-at-rest]\npendiente_verificacion: motivo\n",
                )
            ],
            "challenges and a verificationPending reason at once",
        ),
        (
            [_obligation("OBL-RGPD-32-1", "verificado_por: [sec-encryption-at-rest]\n")],
            "orphan challenge without obligation: ret-table-retention",
        ),
    ],
)
def test_matrix_errors_block_publication(templates: list[str], message: str) -> None:
    _, errors = build_matrix(_graph(*templates), parse_challenge_catalog(CATALOG))
    assert any(message in error for error in errors), errors


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({}, "'challenges' list"),
        ({"challenges": ["sec-x"]}, "must be a mapping"),
        ({"challenges": [{"id": "sec-x", "family": "security"}]}, "misses"),
        ({"challenges": [dict(CATALOG["challenges"][0], id="SEC_X")]}, "invalid challenge id"),
        (
            {"challenges": [dict(CATALOG["challenges"][0], evidence_type="screenshot")]},
            "unknown evidence type",
        ),
        ({"challenges": [CATALOG["challenges"][0], CATALOG["challenges"][0]]}, "repeated"),
    ],
)
def test_invalid_catalogs_are_rejected(document: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_challenge_catalog(document)


def test_the_shipped_catalog_starts_empty_and_valid() -> None:
    assert load_challenge_catalog(CATALOG_FILE) == {}


def test_outputs_are_deterministic_json_and_semicolon_csv() -> None:
    graph = _graph(
        _obligation(
            "OBL-RGPD-32-1", "verificado_por: [sec-encryption-at-rest, ret-table-retention]\n"
        )
    )
    rows, _ = build_matrix(graph, parse_challenge_catalog(CATALOG))
    assert matrix_json(rows) == matrix_json(rows)
    [entry] = json.loads(matrix_json(rows))
    assert entry["challenges"] == ["ret-table-retention", "sec-encryption-at-rest"]
    parsed = list(csv.reader(io.StringIO(matrix_csv(rows)), delimiter=";"))
    assert tuple(parsed[0]) == CSV_COLUMNS
    assert parsed[1][3] == "ret-table-retention,sec-encryption-at-rest"


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ontology_traceability", ROOT / "tools" / "ontology_traceability.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_tool_writes_outputs_and_fails_on_errors(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "ontology" / "norms").mkdir(parents=True)
    (library / "challenges").mkdir()
    catalog = library / "challenges" / "catalog.yaml"
    catalog.write_text(json.dumps({"challenges": CATALOG["challenges"][:1]}), encoding="utf-8")
    norm = library / "ontology" / "norms" / "OBL-RGPD-32-1.ttl"
    norm.write_bytes(
        compile_obligation(
            _obligation("OBL-RGPD-32-1", "verificado_por: [sec-encryption-at-rest]\n")
        )
    )
    output = tmp_path / "dist"
    tool = _tool()
    assert tool.main(["--library", str(library), "--output", str(output)]) == 0
    assert (
        json.loads((output / "traceability.json").read_text(encoding="utf-8"))[0]["status"]
        == "covered"
    )
    catalog.write_text(json.dumps(CATALOG), encoding="utf-8")
    assert tool.main(["--library", str(library), "--output", str(output)]) == 1
