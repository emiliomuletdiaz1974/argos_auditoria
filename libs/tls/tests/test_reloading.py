"""ARG-083 · mutual TLS between ARGOS services, with certificates that change without a restart.

A test CA made here, a real TLS server on 127.0.0.1 in a thread and real clients: a client
without a certificate is refused, one signed by another CA too, nothing below TLS 1.3 is spoken,
and a certificate replaced on disk is the one the next handshake presents, with no restart.
"""

import datetime as dt
import os
import socket
import ssl
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from argos_tls import CA_FILE, CERT_FILE, KEY_FILE, ReloadingTLS, mtls_client

NOW = dt.datetime.now(dt.UTC)


@dataclass
class Authority:
    key: ec.EllipticCurvePrivateKey
    cert: x509.Certificate

    @classmethod
    def new(cls, name: str) -> "Authority":
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(NOW - dt.timedelta(minutes=1))
            .not_valid_after(NOW + dt.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        return cls(key, cert)

    def issue(self, folder: Path, name: str = "localhost") -> int:
        """A leaf for `name` in folder, next to this CA; returns its serial number."""
        key = ec.generate_private_key(ec.SECP256R1())
        serial = x509.random_serial_number()
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(self.cert.subject)
            .public_key(key.public_key())
            .serial_number(serial)
            .not_valid_before(NOW - dt.timedelta(minutes=1))
            .not_valid_after(NOW + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .sign(self.key, hashes.SHA256())
        )
        folder.mkdir(parents=True, exist_ok=True)
        (folder / KEY_FILE).write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        (folder / CERT_FILE).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (folder / CA_FILE).write_bytes(self.cert.public_bytes(serialization.Encoding.PEM))
        return serial


class Server:
    """Accepts TLS connections and answers each with one byte."""

    def __init__(self, tls: ReloadingTLS) -> None:
        self._tls = tls
        self._sock = socket.create_server(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self.errors: list[str] = []
        self._stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        self._sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                raw, _ = self._sock.accept()
            except TimeoutError:
                continue
            try:
                with self._tls.context().wrap_socket(raw, server_side=True) as conn:
                    conn.sendall(b"k")
            except (ssl.SSLError, OSError) as exc:
                self.errors.append(type(exc).__name__)

    def close(self) -> None:
        self._stop.set()
        self._sock.close()


@pytest.fixture
def ca() -> Authority:
    return Authority.new("ARGOS test CA")


@pytest.fixture
def server(ca: Authority, tmp_path: Path) -> Iterator[tuple[Server, Path]]:
    folder = tmp_path / "server"
    ca.issue(folder)
    running = Server(ReloadingTLS(server=True, cert_dir=folder, check_interval=0))
    try:
        yield running, folder
    finally:
        running.close()


def _handshake(port: int, context: ssl.SSLContext) -> int:
    """Connect, read the byte and return the serial number of the server certificate."""
    with (
        socket.create_connection(("127.0.0.1", port), timeout=5) as raw,
        context.wrap_socket(raw, server_hostname="localhost") as conn,
    ):
        assert conn.recv(1) == b"k"
        der = conn.getpeercert(binary_form=True)
    assert der is not None
    return x509.load_der_x509_certificate(der).serial_number


def _client(ca: Authority, tmp_path: Path, name: str = "client") -> ssl.SSLContext:
    folder = tmp_path / name
    ca.issue(folder, "api")
    return ReloadingTLS(server=False, cert_dir=folder).context()


def test_a_client_of_the_same_ca_talks_to_the_server(
    server: tuple[Server, Path], ca: Authority, tmp_path: Path
) -> None:
    running, _ = server
    _handshake(running.port, _client(ca, tmp_path))


def test_a_client_without_a_certificate_is_refused(
    server: tuple[Server, Path], ca: Authority, tmp_path: Path
) -> None:
    running, folder = server
    anonymous = ssl.create_default_context(cafile=str(folder / CA_FILE))
    with pytest.raises((ssl.SSLError, ConnectionError, AssertionError)):
        _handshake(running.port, anonymous)


def test_a_client_of_another_ca_is_refused(
    server: tuple[Server, Path], ca: Authority, tmp_path: Path
) -> None:
    running, folder = server
    stranger = Authority.new("somebody else")
    stranger.issue(tmp_path / "stranger", "api")
    context = ssl.create_default_context(cafile=str(folder / CA_FILE))
    context.load_cert_chain(tmp_path / "stranger" / CERT_FILE, tmp_path / "stranger" / KEY_FILE)
    with pytest.raises((ssl.SSLError, ConnectionError, AssertionError)):
        _handshake(running.port, context)


def test_a_server_of_another_ca_is_refused_by_the_client(ca: Authority, tmp_path: Path) -> None:
    stranger = Authority.new("somebody else")
    stranger.issue(tmp_path / "fake-server")
    fake = Server(ReloadingTLS(server=True, cert_dir=tmp_path / "fake-server"))
    try:
        with pytest.raises(ssl.SSLCertVerificationError):
            _handshake(fake.port, _client(ca, tmp_path))
    finally:
        fake.close()


def test_nothing_below_tls_1_3_is_spoken(
    server: tuple[Server, Path], ca: Authority, tmp_path: Path
) -> None:
    running, _ = server
    old = _client(ca, tmp_path)
    old.minimum_version = ssl.TLSVersion.TLSv1_2
    old.maximum_version = ssl.TLSVersion.TLSv1_2
    with pytest.raises((ssl.SSLError, ConnectionError)):
        _handshake(running.port, old)


def test_a_certificate_replaced_on_disk_is_served_without_a_restart(
    server: tuple[Server, Path], ca: Authority, tmp_path: Path
) -> None:
    running, folder = server
    client = _client(ca, tmp_path)
    before = _handshake(running.port, client)
    renewed = ca.issue(folder)
    later = os.stat(folder / CERT_FILE).st_mtime + 5  # a later mtime, whatever the clock says
    os.utime(folder / CERT_FILE, (later, later))
    after = _handshake(running.port, client)
    assert before != renewed
    assert after == renewed


def test_the_client_context_verifies_the_server_and_presents_its_certificate(
    ca: Authority, tmp_path: Path
) -> None:
    context = _client(ca, tmp_path)
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname
    assert context.minimum_version is ssl.TLSVersion.TLSv1_3


def test_the_http_client_carries_the_context(ca: Authority, tmp_path: Path) -> None:
    ca.issue(tmp_path / "client", "api")
    with mtls_client(tmp_path / "client", base_url="https://ai-gateway:8005") as client:
        assert str(client.base_url) == "https://ai-gateway:8005"


def test_the_issuer_renews_at_two_thirds_of_the_life(ca: Authority, tmp_path: Path) -> None:
    from argos_tls.issuer import due

    ca.issue(tmp_path / "svc")
    cert = x509.load_pem_x509_certificate((tmp_path / "svc" / CERT_FILE).read_bytes())
    start, end = cert.not_valid_before_utc, cert.not_valid_after_utc
    life = end - start
    assert not due(tmp_path / "svc" / CERT_FILE, start + life * 0.6)
    assert due(tmp_path / "svc" / CERT_FILE, start + life * 0.7)
    assert due(tmp_path / "missing" / CERT_FILE, start)


def test_the_issuer_reads_its_services() -> None:
    from argos_tls.issuer import parse_services

    requests = parse_services("api=api; postgres=postgres,127.0.0.1")
    assert [(r.folder, r.common_name, r.names) for r in requests] == [
        ("api", "api", ("api",)),
        ("postgres", "postgres", ("postgres", "127.0.0.1")),
    ]
    with pytest.raises(ValueError, match="folder"):
        parse_services("api=")
