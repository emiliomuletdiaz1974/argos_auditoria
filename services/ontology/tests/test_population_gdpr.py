"""GDPR population: verifiable obligations of the approved v1 scope, pending legal validation."""

from pathlib import Path

import yaml
from rdflib import RDF, Graph

from argos_ontology.editorial.compiler import ObligationSpec, parse_obligation
from argos_ontology.editorial.translation import read_editorial, to_internal
from argos_ontology.gates import EDITORIAL_DIR, TEMPLATE_NAME
from argos_ontology.traceability import build_matrix, library_graph, load_challenge_catalog
from argos_ontology.vocabulary import ARGOS, LIBRARY_DIR, NORMS

NORM_FILE = LIBRARY_DIR / "ontology" / "norms" / "RGPD.ttl"
# Approved v1 blocks (F04-00): data subject rights, security, record of processing, breaches;
# the article 5 principles anchor retention and confidentiality, which the phase 05 challenges cite.
SCOPE = {
    "5.1.e": "principles",
    "5.1.f": "principles",
    "9.1": "record",
    "15": "rights",
    "17": "rights",
    "30.1": "record",
    "30.1.c": "record",
    "30.1.f": "record",
    "32.1.a": "security",
    "32.1.b": "security",
    "33.1": "breaches",
    "33.5": "breaches",
}


def _templates() -> list[Path]:
    return sorted(
        p for p in (LIBRARY_DIR / EDITORIAL_DIR).glob("OBL-RGPD-*.yaml") if p.name != TEMPLATE_NAME
    )


def _specs() -> dict[str, ObligationSpec]:
    return {
        p.stem: parse_obligation(to_internal(read_editorial(p.read_text(encoding="utf-8"))))
        for p in _templates()
    }


def test_every_template_is_named_after_its_id_and_stays_in_the_approved_scope() -> None:
    specs = _specs()
    assert len(specs) == 13
    for stem, spec in specs.items():
        assert spec.id == stem
        assert spec.norm == "RGPD"
        assert spec.article in SCOPE, spec
        assert spec.summary, f"{stem} needs a summary the legal profile can validate"


def test_every_block_of_the_scope_is_populated() -> None:
    blocks = {SCOPE[spec.article] for spec in _specs().values()}
    assert blocks == {"principles", "rights", "security", "record", "breaches"}


def test_every_cited_article_is_declared_as_part_of_the_norm() -> None:
    norm = Graph().parse(NORM_FILE, format="turtle")
    assert (NORMS["RGPD"], RDF.type, ARGOS.Norm) in norm
    for article in SCOPE:
        node = NORMS[f"RGPD-{article.replace('.', '-')}"]
        assert (node, ARGOS.partOf, NORMS["RGPD"]) in norm, article


def test_every_referenced_challenge_is_in_the_catalog() -> None:
    catalog = load_challenge_catalog()
    referenced = {c for spec in _specs().values() for c in spec.verified_by}
    assert referenced and referenced <= set(catalog)


def test_only_the_breach_notification_drill_is_pending() -> None:
    rows, errors = build_matrix(library_graph(), load_challenge_catalog())
    assert errors == []
    gdpr = {
        row.obligation.removeprefix(str(NORMS)): row.status
        for row in rows
        if row.obligation.startswith(str(NORMS["OBL-RGPD-"]))
    }
    assert len(gdpr) == 13
    assert [k for k, v in gdpr.items() if v == "pending"] == ["OBL-RGPD-33-1"]


def test_the_catalog_file_stays_plain_yaml_with_a_challenges_list() -> None:
    document = yaml.safe_load((LIBRARY_DIR / "challenges" / "catalog.yaml").read_text("utf-8"))
    assert [entry["id"] for entry in document["challenges"]] == sorted(
        entry["id"] for entry in document["challenges"]
    )
