"""Quality review QA-01 · the certificate issuer in its edge cases (QA-003, QA-011).

One service that cannot be renewed does not stop the renewal of the ones listed after it, and a
key and a certificate that do not belong together (a cut between the two writes) are issued again
instead of leaving the service unable to start.
"""

import datetime as dt
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from argos_tls import CA_FILE, CERT_FILE, KEY_FILE
from argos_tls.issuer import Request, renew

NOW = dt.datetime(2026, 9, 28, tzinfo=dt.UTC)
ROOT = "-----BEGIN CERTIFICATE-----\nROOT\n-----END CERTIFICATE-----"


def _pair(name: str) -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - dt.timedelta(days=1))
        .not_valid_after(NOW + dt.timedelta(days=29))
        .sign(key, hashes.SHA256())
    )
    pem_cert = cert.public_bytes(serialization.Encoding.PEM).decode()
    pem_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem_cert, pem_key


class FakeVault:
    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.issued: list[str] = []

    def root(self) -> str:
        return ROOT

    def issue(self, request: Request) -> tuple[str, str, str]:
        if request.folder in self.failing:
            raise httpx.HTTPError(f"vault refused {request.folder}")
        self.issued.append(request.folder)
        cert, key = _pair(request.common_name)
        return cert, key, ROOT + "\n"


def test_one_service_that_fails_does_not_stop_the_others(tmp_path: Path) -> None:
    vault = FakeVault(failing={"api"})
    requests = [Request("api", ("api",)), Request("nats", ("nats",)), Request("vault", ("vault",))]
    renewed = renew(vault, tmp_path, requests, NOW)  # type: ignore[arg-type]
    assert renewed == ["nats", "vault"]


def test_a_key_that_does_not_match_its_certificate_is_issued_again(tmp_path: Path) -> None:
    folder = tmp_path / "api"
    folder.mkdir()
    cert, _ = _pair("api")
    _, other_key = _pair("api")  # a cut between the two writes: the key of another issue
    (folder / CERT_FILE).write_text(cert, encoding="utf-8")
    (folder / KEY_FILE).write_text(other_key, encoding="utf-8")
    (folder / CA_FILE).write_text(ROOT + "\n", encoding="utf-8")
    vault = FakeVault(failing=set())
    assert renew(vault, tmp_path, [Request("api", ("api",))], NOW) == ["api"]  # type: ignore[arg-type]
