"""The QR of a printed dossier opens a page: the public verifier answers the GET of `/verify`.

The QR carries `<verifier of the environment>/verify?dossier=<SHA-256>`. Scanned with a phone, it
used to get a 405: the route only took the POST of a bundle. Now the GET says which dossier that is
and how to check it, and the POST keeps doing the check.
"""

from fastapi.testclient import TestClient

from argos_verifier.api import app

DIGEST = "ab" * 32
client = TestClient(app)


def test_the_qr_of_a_dossier_opens_a_page_with_its_hash_and_how_to_check_it() -> None:
    answer = client.get(f"/verify?dossier={DIGEST}")
    assert answer.status_code == 200, answer.text
    assert answer.headers["content-type"].startswith("text/html")
    page = answer.text
    assert DIGEST in page
    assert "paquete de verificación" in page and "verify_evidence.py" in page
    assert 'href="/norms/"' in page, "the catalogue of the obligations it cites"
    assert "<script" not in page
    assert "default-src 'none'" in answer.headers["content-security-policy"]


def test_a_code_that_is_not_a_hash_is_not_echoed() -> None:
    answer = client.get("/verify?dossier=<b>hola</b>")
    assert answer.status_code == 400
    assert "<b>hola</b>" not in answer.text and "hola" not in answer.text


def test_without_a_code_the_page_still_explains_the_check() -> None:
    answer = client.get("/verify")
    assert answer.status_code == 200 and "paquete de verificación" in answer.text


def test_the_check_itself_is_still_the_post() -> None:
    assert client.post("/verify", content=b"not json").status_code == 400
