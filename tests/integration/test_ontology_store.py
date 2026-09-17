"""ARG-032 · immutable ontology versions in PostgreSQL, answered by date, with SPARQL."""

import hashlib
from datetime import date

import psycopg
import pytest
from rdflib import OWL, RDF, Graph, Literal, URIRef

from argos_ontology.store import (
    BundleConflictError,
    OntologyStore,
    bundle_record,
    store_version,
    version_in_force,
)
from argos_ontology.vocabulary import ARGOS, CLASSES, load_core

pytestmark = pytest.mark.integration

SHAPE = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix g: <urn:argos:graph:> .
g:TreatmentShape a sh:NodeShape ;
  sh:targetClass g:Treatment ;
  sh:property [ sh:path g:legal_basis ; sh:minCount 1 ; sh:message "Sin base jurídica"@es ] .
"""
CLASSES_QUERY = "PREFIX owl: <http://www.w3.org/2002/07/owl#> SELECT ?c WHERE { ?c a owl:Class }"


def _hash(graph: Graph) -> str:
    return hashlib.sha256(graph.serialize(format="nt", encoding="utf-8")).hexdigest()


def _store(dsn: str, version: str, in_force: date, graph: Graph) -> str:
    manifest = {"version": version, "in_force_from": in_force.isoformat()}
    store_version(dsn, version, in_force, graph, _hash(graph), manifest, b"signature")
    return version


def test_a_version_is_stored_queried_and_journaled(migrated_db: str) -> None:
    core = load_core()
    record = store_version(
        migrated_db, "1.0.0", date(2026, 1, 1), core, _hash(core), {"version": "1.0.0"}, b"sig"
    )
    assert record.quads == len(core)
    store = OntologyStore(migrated_db, version="1.0.0")
    classes = {row[0] for row in store.sparql(CLASSES_QUERY)}
    assert classes == {ARGOS[name] for name in CLASSES}
    assert store.graph.isomorphic(core)
    with psycopg.connect(migrated_db) as conn:
        entries = conn.execute(
            "SELECT payload->>'version', (payload->>'quads')::int FROM argos.audit_journal "
            "WHERE action = 'ontology.load'"
        ).fetchall()
    assert entries == [("1.0.0", len(core))]


def test_loading_the_same_content_twice_is_a_no_op(migrated_db: str) -> None:
    core = load_core()
    first = store_version(migrated_db, "1.0.0", date(2026, 1, 1), core, _hash(core), {}, b"s")
    again = store_version(migrated_db, "1.0.0", date(2026, 1, 1), core, _hash(core), {}, b"s")
    assert again == first
    with psycopg.connect(migrated_db) as conn:
        [(quads, loads)] = conn.execute(
            "SELECT (SELECT count(*) FROM argos.ontology_quads), "
            "(SELECT count(*) FROM argos.audit_journal WHERE action = 'ontology.load')"
        ).fetchall()
    assert (quads, loads) == (len(core), 1)


def test_a_version_cannot_be_reloaded_with_other_content(migrated_db: str) -> None:
    core = load_core()
    store_version(migrated_db, "1.0.0", date(2026, 1, 1), core, _hash(core), {}, b"s")
    with pytest.raises(BundleConflictError, match="1.0.0"):
        store_version(migrated_db, "1.0.0", date(2026, 1, 1), core, "b" * 64, {}, b"s")


def test_the_version_in_force_follows_the_manifest_date_not_the_load_order(
    migrated_db: str,
) -> None:
    core = load_core()
    _store(migrated_db, "1.1.0", date(2026, 6, 1), core)
    _store(migrated_db, "1.0.0", date(2026, 1, 1), core)  # loaded later, in force earlier
    assert version_in_force(migrated_db, date(2026, 3, 3)) == "1.0.0"
    assert version_in_force(migrated_db, date(2026, 6, 1)) == "1.1.0"
    assert OntologyStore(migrated_db, at=date(2026, 3, 3)).version == "1.0.0"
    with pytest.raises(LookupError, match="2025-12-31"):
        version_in_force(migrated_db, date(2025, 12, 31))
    with pytest.raises(LookupError, match="unknown ontology version"):
        bundle_record(migrated_db, "9.9.9")


def test_versions_are_immutable(migrated_db: str) -> None:
    _store(migrated_db, "1.0.0", date(2026, 1, 1), load_core())
    for statement in (
        "UPDATE argos.ontology_bundles SET in_force_from = '2020-01-01'",
        "DELETE FROM argos.ontology_quads",
        "TRUNCATE argos.ontology_bundles CASCADE",
    ):
        with psycopg.connect(migrated_db) as conn, pytest.raises(psycopg.errors.RaiseException):
            conn.execute(statement)


def test_blank_nodes_languages_and_datatypes_survive_storage(migrated_db: str) -> None:
    graph = Graph().parse(data=SHAPE, format="turtle")
    graph.add((ARGOS.Obligation, ARGOS.inForceFrom, Literal(date(2018, 5, 25))))
    _store(migrated_db, "2.0.0", date(2026, 1, 1), graph)
    assert OntologyStore(migrated_db, version="2.0.0").graph.isomorphic(graph)


def test_bindings_are_typed_terms_never_guessed(migrated_db: str) -> None:
    graph = Graph()
    iri = URIRef("http://example.org/thing")
    graph.add((iri, RDF.type, OWL.Class))
    graph.add((ARGOS.Note, ARGOS.graphLabel, Literal("http://example.org/thing")))
    _store(migrated_db, "3.0.0", date(2026, 1, 1), graph)
    store = OntologyStore(migrated_db, version="3.0.0")
    typed = store.sparql("SELECT ?s WHERE { ?s ?p ?o }", {"o": OWL.Class})
    assert [row[0] for row in typed] == [iri]
    literal = store.sparql(
        "SELECT ?s WHERE { ?s ?p ?o }", {"o": Literal("http://example.org/thing")}
    )
    assert [row[0] for row in literal] == [ARGOS.Note]
