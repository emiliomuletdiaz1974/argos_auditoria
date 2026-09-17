"""ARG-031 · the core ontology file and its code-side vocabulary stay aligned."""

import pytest
from rdflib import OWL, RDF, RDFS, Literal, URIRef

from argos_ontology.vocabulary import (
    ARGOS,
    CLASSES,
    DATATYPE_PROPERTIES,
    EVIDENCE_TYPES,
    OBJECT_PROPERTIES,
    ONTOLOGY_VERSION,
    load_core,
)

CORE = load_core()


def test_core_is_an_owl_ontology_with_its_version() -> None:
    ontology = URIRef(str(ARGOS))
    assert (ontology, RDF.type, OWL.Ontology) in CORE
    assert CORE.value(ontology, OWL.versionInfo) == Literal(ONTOLOGY_VERSION)


@pytest.mark.parametrize("name", CLASSES)
def test_every_class_is_declared_with_a_spanish_label(name: str) -> None:
    term = ARGOS[name]
    assert (term, RDF.type, OWL.Class) in CORE
    labels = [label for label in CORE.objects(term, RDFS.label) if isinstance(label, Literal)]
    assert any(label.language == "es" for label in labels)


@pytest.mark.parametrize(("name", "domain_range"), sorted(OBJECT_PROPERTIES.items()))
def test_object_properties_keep_their_domain_and_range(
    name: str, domain_range: tuple[str | None, str | None]
) -> None:
    term = ARGOS[name]
    domain, range_ = domain_range
    assert (term, RDF.type, OWL.ObjectProperty) in CORE
    if domain is not None:
        assert CORE.value(term, RDFS.domain) == ARGOS[domain]
    if range_ is not None:
        assert CORE.value(term, RDFS.range) == ARGOS[range_]


def test_equivalence_between_frameworks_is_symmetric() -> None:
    assert (ARGOS.equivalentTo, RDF.type, OWL.SymmetricProperty) in CORE


@pytest.mark.parametrize("name", DATATYPE_PROPERTIES)
def test_datatype_properties_are_declared(name: str) -> None:
    assert (ARGOS[name], RDF.type, OWL.DatatypeProperty) in CORE


def test_evidence_types_are_the_closed_list() -> None:
    declared = {
        str(s).removeprefix(str(ARGOS)) for s in CORE.subjects(RDF.type, ARGOS.EvidenceType)
    }
    assert declared == set(EVIDENCE_TYPES)


def test_the_core_declares_nothing_outside_the_vocabulary() -> None:
    expected = {
        *CLASSES,
        *OBJECT_PROPERTIES,
        *DATATYPE_PROPERTIES,
        *EVIDENCE_TYPES,
        "",
    }
    declared = {
        str(s).removeprefix(str(ARGOS)) for s in CORE.subjects() if str(s).startswith(str(ARGOS))
    }
    assert declared == expected


def test_every_label_carries_a_language_tag() -> None:
    for label in CORE.objects(None, RDFS.label):
        assert isinstance(label, Literal) and label.language == "es", label
