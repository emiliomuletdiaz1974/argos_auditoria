"""The IRIs of the norms namespace resolve: a person reads a page, a program reads the RDF.

Findings and the signed evidence carry `https://ns.argos.eu/norms/OBL-…`. Whoever serves that
namespace answers `/norms/{name}` with the description of that node, and the links of the page stay
on the host that served it, so the same build works on the bench name and on `ns.argos.eu`.
"""

import json

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, URIRef

from argos_verifier.api import app
from argos_verifier.norms import ONTOLOGY_DIR

IRI = "https://ns.argos.eu/norms/OBL-RGPD-32-3"
client = TestClient(app)


def test_a_person_opening_the_iri_of_an_obligation_reads_it() -> None:
    answer = client.get("/norms/OBL-RGPD-32-3", headers={"Accept": "text/html"})
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("text/html")
    page = answer.text
    assert "Cifrado en tránsito hacia los sistemas con datos personales" in page
    assert "Artículo 32.1.b" in page, "the article it derives from, by its label"
    assert "Reglamento General de Protección de Datos" in page, "and the norm of the article"
    assert "http://data.europa.eu/eli/reg/2016/679/oj" in page, "the official text of the norm"
    assert "sec-encryption-in-transit" in page and "2018-05-25" in page
    assert IRI in page, "the page says which IRI it describes"
    assert 'href="/norms/RGPD-32-1-b"' in page, "links stay on the host that served the page"
    assert 'https://ns.argos.eu/norms/RGPD-32-1-b"' not in page


def test_the_page_forbids_scripts_and_being_framed() -> None:
    answer = client.get("/norms/OBL-RGPD-32-3")
    policy = answer.headers["content-security-policy"]
    assert "default-src 'none'" in policy and "frame-ancestors 'none'" in policy
    assert answer.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("kind", ["text/turtle", "application/ld+json"])
def test_a_program_asking_for_rdf_gets_the_triples_of_the_node(kind: str) -> None:
    answer = client.get("/norms/OBL-RGPD-32-3", headers={"Accept": kind})
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith(kind)
    graph = Graph().parse(data=answer.text, format="turtle" if kind == "text/turtle" else "json-ld")
    subjects = {str(s) for s in graph.subjects()}
    assert IRI in subjects
    assert (URIRef(IRI), None, None) in graph
    if kind == "application/ld+json":
        json.loads(answer.text)


def test_the_article_and_the_norm_resolve_as_well() -> None:
    article = client.get("/norms/RGPD-32-1-b", headers={"Accept": "text/html"})
    assert article.status_code == 200 and "Artículo 32.1.b" in article.text
    norm = client.get("/norms/RGPD", headers={"Accept": "text/html"})
    assert norm.status_code == 200 and "data.europa.eu/eli/reg/2016/679/oj" in norm.text


@pytest.mark.parametrize("name", ["OBL-RGPD-99-9", "..%2Fsecrets", "OBL-RGPD-32-3.ttl", "a" * 300])
def test_what_the_namespace_does_not_have_is_a_404(name: str) -> None:
    assert client.get(f"/norms/{name}").status_code == 404


def test_markup_in_the_content_is_shown_as_text() -> None:
    from argos_verifier.norms import page

    graph = Graph().parse(
        data="@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> . "
        '<https://ns.argos.eu/norms/X> rdfs:label "<script>alert(1)</script>"@es .',
        format="turtle",
    )
    html = page(graph, URIRef("https://ns.argos.eu/norms/X"))
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_every_link_of_every_obligation_page_opens() -> None:
    """A page that links to a node the namespace does not serve would send its reader to a 404."""
    import re

    from argos_verifier.norms import ONTOLOGY_DIR

    names = [p.stem for p in (ONTOLOGY_DIR / "norms" / "generated").glob("OBL-*.ttl")]
    assert len(names) > 30
    seen: set[str] = set()
    for name in names:
        page = client.get(f"/norms/{name}").text
        seen.update(re.findall(r'href="/norms/([^"]+)"', page))
    missing = sorted(n for n in seen if client.get(f"/norms/{n}").status_code != 200)
    assert missing == []


def test_the_official_text_of_the_norm_is_a_link() -> None:
    page = client.get("/norms/OBL-RGPD-32-3").text
    assert 'href="http://data.europa.eu/eli/reg/2016/679/oj"' in page


# ---------- the catalogue: an index of every norm and obligation, and its downloads ----------

PENDING = "pendiente de validación jurídica"


def test_the_front_page_lists_every_norm_with_its_obligations_and_official_text() -> None:
    answer = client.get("/norms/", headers={"Accept": "text/html"})
    assert answer.status_code == 200, answer.text
    page = answer.text
    for norm in ("RGPD", "EHDS", "AIACT", "SELF"):
        assert f'href="/norms/{norm}"' in page
    for path in (ONTOLOGY_DIR / "norms" / "generated").glob("OBL-*.ttl"):
        assert f'href="/norms/{path.stem}"' in page, f"{path.stem} missing from the index"
    assert "http://data.europa.eu/eli/reg/2024/1689/oj" in page
    assert PENDING in page, "the population is not legally validated yet (F04-13, 15, 17)"


def test_every_page_carries_the_index_the_downloads_and_the_notice() -> None:
    page = client.get("/norms/OBL-RGPD-32-3").text
    assert 'href="/norms/catalogo.pdf"' in page and 'href="/norms/catalogo.md"' in page
    assert 'href="/norms/OBL-AIACT-' in page, "the index reaches the other norms"
    assert 'aria-current="page" href="/norms/OBL-RGPD-32-3"' in page
    assert PENDING in page
    assert "<script" not in page


def test_the_catalogue_downloads_as_markdown() -> None:
    answer = client.get("/norms/catalogo.md")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/markdown")
    assert "attachment" in answer.headers["content-disposition"]
    text = answer.text
    assert text.startswith("# ")
    assert "## Reglamento General de Protección de Datos" in text
    assert "### OBL-RGPD-32-3 · Cifrado en tránsito hacia los sistemas con datos personales" in text
    assert "https://ns.argos.eu/norms/OBL-RGPD-32-3" in text
    assert PENDING in text
    count = len(list((ONTOLOGY_DIR / "norms" / "generated").glob("OBL-*.ttl")))
    assert text.count("\n### OBL-") == count


def test_the_catalogue_downloads_as_pdf() -> None:
    answer = client.get("/norms/catalogo.pdf")
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/pdf"
    assert "attachment" in answer.headers["content-disposition"]
    assert answer.content.startswith(b"%PDF-") and len(answer.content) > 5_000
