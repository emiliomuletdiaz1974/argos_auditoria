"""EHDS population: primary and secondary use obligations of the v1, pending legal validation."""

from datetime import date

from rdflib import RDF, Graph

from argos_ontology.editorial.compiler import ObligationSpec, parse_obligation
from argos_ontology.editorial.translation import read_editorial, to_internal
from argos_ontology.gates import EDITORIAL_DIR
from argos_ontology.traceability import build_matrix, library_graph, load_challenge_catalog
from argos_ontology.vocabulary import ARGOS, LIBRARY_DIR, NORMS

NORM_FILE = LIBRARY_DIR / "ontology" / "norms" / "EHDS.ttl"
# Approved v1 blocks (F04-00): primary use (chapter II) and secondary use (chapter IV).
SCOPE = {
    "3": "primary",
    "8": "primary",
    "9.2": "primary",
    "11.1": "primary",
    "13.1": "primary",
    "60.2": "secondary",
    "60.3": "secondary",
}
# Regulation (EU) 2025/327, art. 105: arts. 3-15 and chapter IV apply from 26 March 2029.
APPLICATION = date(2029, 3, 26)


def _specs() -> dict[str, ObligationSpec]:
    return {
        p.stem: parse_obligation(to_internal(read_editorial(p.read_text(encoding="utf-8"))))
        for p in sorted((LIBRARY_DIR / EDITORIAL_DIR).glob("OBL-EHDS-*.yaml"))
    }


def test_every_template_is_named_after_its_id_and_stays_in_the_approved_scope() -> None:
    specs = _specs()
    assert len(specs) == 7
    for stem, spec in specs.items():
        assert spec.id == stem
        assert spec.norm == "EHDS"
        assert spec.article in SCOPE, spec
        assert spec.summary, f"{stem} needs a summary the legal profile can validate"


def test_both_uses_are_populated() -> None:
    assert {SCOPE[spec.article] for spec in _specs().values()} == {"primary", "secondary"}


def test_obligations_apply_from_the_dates_of_article_105_not_from_entry_into_force() -> None:
    assert {spec.in_force_from for spec in _specs().values()} == {APPLICATION}


def test_every_cited_article_is_declared_as_part_of_the_norm() -> None:
    norm = Graph().parse(NORM_FILE, format="turtle")
    assert (NORMS["EHDS"], RDF.type, ARGOS.Norm) in norm
    for article in SCOPE:
        node = NORMS[f"EHDS-{article.replace('.', '-')}"]
        assert (node, ARGOS.partOf, NORMS["EHDS"]) in norm, article


def test_every_referenced_challenge_is_in_the_catalog() -> None:
    catalog = load_challenge_catalog()
    referenced = {c for spec in _specs().values() for c in spec.verified_by}
    assert referenced and referenced <= set(catalog)


def test_only_the_data_access_body_deadline_is_pending() -> None:
    rows, errors = build_matrix(library_graph(), load_challenge_catalog())
    assert errors == []
    ehds = {
        row.obligation.removeprefix(str(NORMS)): row.status
        for row in rows
        if row.obligation.startswith(str(NORMS["OBL-EHDS-"]))
    }
    assert len(ehds) == 7
    assert [k for k, v in ehds.items() if v == "pending"] == ["OBL-EHDS-60-1"]
