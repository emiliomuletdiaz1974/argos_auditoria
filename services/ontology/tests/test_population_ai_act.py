"""AI Act population: demonstrable obligations on AI systems of the v1, pending legal validation."""

from datetime import date

from rdflib import RDF, Graph

from argos_ontology.applicability import asset_classes, compiled_selector, load_asset_classes
from argos_ontology.editorial.compiler import ObligationSpec, parse_obligation
from argos_ontology.editorial.translation import read_editorial, to_internal
from argos_ontology.gates import EDITORIAL_DIR
from argos_ontology.traceability import build_matrix, library_graph, load_challenge_catalog
from argos_ontology.vocabulary import ARGOS, LIBRARY_DIR, NORMS

NORM_FILE = LIBRARY_DIR / "ontology" / "norms" / "AIACT.ttl"
# Approved v1 (F04-00): demonstrable high-risk requirements (logging, technical documentation,
# data governance), plus the prohibitions and the classification they depend on.
SCOPE = {
    "5.1": "prohibitions",
    "6": "classification",
    "10.2.b": "high_risk",
    "11.1": "high_risk",
    "12.1": "high_risk",
    "26.2": "deployer",
    "26.6": "deployer",
}
# Regulation (EU) 2024/1689, art. 113: chapters I-II from 2 February 2025, general application
# from 2 August 2026 (article 6.1 systems from 2 August 2027).
DATES = {"prohibitions": date(2025, 2, 2)}
GENERAL = date(2026, 8, 2)


def _specs() -> dict[str, ObligationSpec]:
    return {
        p.stem: parse_obligation(to_internal(read_editorial(p.read_text(encoding="utf-8"))))
        for p in sorted((LIBRARY_DIR / EDITORIAL_DIR).glob("OBL-AIACT-*.yaml"))
    }


def test_every_template_is_named_after_its_id_and_stays_in_the_approved_scope() -> None:
    specs = _specs()
    assert len(specs) == 8
    for stem, spec in specs.items():
        assert spec.id == stem
        assert spec.norm == "AIACT"
        assert spec.article in SCOPE, spec
        assert spec.summary, f"{stem} needs a summary the legal profile can validate"


def test_every_block_is_populated() -> None:
    blocks = {SCOPE[spec.article] for spec in _specs().values()}
    assert blocks == {"prohibitions", "classification", "high_risk", "deployer"}


def test_obligations_apply_from_the_dates_of_article_113() -> None:
    for spec in _specs().values():
        assert spec.in_force_from == DATES.get(SCOPE[spec.article], GENERAL), spec.id


def test_confirmed_ai_systems_have_their_own_asset_class() -> None:
    by_name = {
        str(ac.iri).removeprefix(str(NORMS)): ac for ac in asset_classes(load_asset_classes())
    }
    assert compiled_selector(by_name["AC-confirmed-ai-system"]).status == "confirmed"


def test_every_cited_article_is_declared_as_part_of_the_norm() -> None:
    norm = Graph().parse(NORM_FILE, format="turtle")
    assert (NORMS["AIACT"], RDF.type, ARGOS.Norm) in norm
    for article in SCOPE:
        node = NORMS[f"AIACT-{article.replace('.', '-')}"]
        assert (node, ARGOS.partOf, NORMS["AIACT"]) in norm, article


def test_every_obligation_is_covered_by_a_catalog_challenge() -> None:
    catalog = load_challenge_catalog()
    referenced = {c for spec in _specs().values() for c in spec.verified_by}
    assert referenced and referenced <= set(catalog)
    rows, errors = build_matrix(library_graph(), load_challenge_catalog())
    assert errors == []
    statuses = {
        row.obligation: row.status
        for row in rows
        if row.obligation.startswith(str(NORMS["OBL-AIACT-"]))
    }
    assert len(statuses) == 8
    assert set(statuses.values()) == {"covered"}
