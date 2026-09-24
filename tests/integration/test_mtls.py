"""ARG-083 · mutual TLS inside ARGOS, checked against the running environment (F09-06).

From a container without a client certificate the AI gateway does not answer; with the certificate
of the API it does. PostgreSQL refuses a connection without TLS, and the client refuses a server it
cannot verify. NATS refuses a client without a certificate. Each container holds only its own key.

Security review F09-02, SEC-026: each NATS user of a service may only create and read its own
consumers on its own stream, never create or change a stream, and the inventory no longer
publishes on argos.campaign.>.
"""

import asyncio
import datetime as dt
import ssl
import subprocess
from pathlib import Path

import nats
import psycopg
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from nats.errors import Error as NatsError

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", str(REPO / "deploy" / "dev" / "compose.yaml")]
HOST_TLS = REPO / "deploy" / "dev" / "secrets" / "tls-host"
PG = "postgresql://argos@127.0.0.1:55432/argos?connect_timeout=5"
# How ARGOS connects (.env.example, compose): the server is verified with the internal CA.
PG_VERIFIED = f"{PG}&sslmode=verify-full&sslrootcert={HOST_TLS / 'ca.crt'}"
NATS_URL = "tls://127.0.0.1:4222"


def _inside(container: str, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed command against the development environment
        [*COMPOSE, "exec", "-T", container, "/app/.venv/bin/python", "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )


GATEWAY_WITHOUT_CERTIFICATE = """
import ssl, httpx
ca_only = ssl.create_default_context(cafile="/run/tls/ca.crt")
try:
    httpx.get("https://ai-gateway:8005/health", verify=ca_only, timeout=5)
    print("ANSWERED")
except (httpx.HTTPError, ssl.SSLError, OSError) as exc:
    print("REFUSED", type(exc).__name__)
"""

GATEWAY_WITH_CERTIFICATE = """
from argos_tls import mtls_client
with mtls_client("/run/tls", timeout=5) as client:
    print(client.get("https://ai-gateway:8005/health").status_code)
"""

OWN_CERTIFICATE = """
from cryptography import x509
cert = x509.load_pem_x509_certificate(open("/run/tls/tls.crt", "rb").read())
print(cert.subject.rfc4514_string())
"""


def test_the_gateway_does_not_answer_a_client_without_a_certificate() -> None:
    probe = _inside("api", GATEWAY_WITHOUT_CERTIFICATE)
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.startswith("REFUSED"), probe.stdout


def test_the_gateway_answers_the_api_with_its_certificate() -> None:
    probe = _inside("api", GATEWAY_WITH_CERTIFICATE)
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "200"


@pytest.mark.parametrize(
    ("container", "name"),
    [("api", "api"), ("ai-gateway", "ai-gateway"), ("challenge-worker", "challenge")],
)
def test_each_container_holds_only_its_own_certificate(container: str, name: str) -> None:
    probe = _inside(container, OWN_CERTIFICATE)
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == f"CN={name}"


def test_postgresql_refuses_a_connection_without_tls() -> None:
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(PG, sslmode="disable")


def _stranger_ca(path: Path) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "somebody else")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def test_the_postgresql_client_refuses_a_server_it_cannot_verify(tmp_path: Path) -> None:
    stranger = tmp_path / "other-ca.crt"
    _stranger_ca(stranger)
    with pytest.raises(psycopg.OperationalError, match="certificate verify failed"):
        psycopg.connect(PG, sslmode="verify-full", sslrootcert=str(stranger))


def test_postgresql_speaks_tls_and_is_verified_with_the_internal_ca() -> None:
    with psycopg.connect(PG_VERIFIED) as conn:
        row = conn.execute(
            "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
        ).fetchone()
    assert row == (True, "TLSv1.3")


def _tls(certificate: bool = True) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(HOST_TLS / "ca.crt"))
    if certificate:
        context.load_cert_chain(HOST_TLS / "tls.crt", HOST_TLS / "tls.key")
    return context


def test_nats_refuses_a_client_without_a_certificate() -> None:
    async def attempt() -> None:
        nc = await nats.connect(
            NATS_URL,
            tls=_tls(certificate=False),
            tls_hostname="127.0.0.1",
            user="argos-dev",
            password="dev-only-nats-host",  # noqa: S106 - development password
            allow_reconnect=False,
            connect_timeout=5,
        )
        await nc.close()

    with pytest.raises((NatsError, ssl.SSLError, OSError)):
        asyncio.run(attempt())


# SEC-026: what each service user may do on JetStream, and what not.
USERS = {
    "inventory": ("dev-only-nats-inventory", "DISCOVERY", "inventory-ingest", "argos.discovery.>"),
    "challenge": (
        "dev-only-nats-challenge",
        "CHALLENGE",
        "campaign-circuit",
        "argos.campaign.circuit_open",
    ),
    "evidence": (
        "dev-only-nats-evidence",
        "CHALLENGE",
        "evidence-on-seal",
        "argos.campaign.sealed",
    ),
    "webhook": (
        "dev-only-nats-webhook",
        "CHALLENGE",
        "webhooks-campaign_sealed",
        "argos.campaign.sealed",
    ),
}


async def _allowed(user: str, password: str, subject: str, payload: bytes = b"{}") -> bool:
    """Whether the server answers a request of this user instead of denying it."""
    nc = await nats.connect(
        NATS_URL,
        tls=_tls(),
        tls_hostname="127.0.0.1",
        user=user,
        password=password,
        allow_reconnect=False,
        connect_timeout=5,
    )
    try:
        reply = await nc.request(subject, payload, timeout=2)
        return b"permission" not in reply.data.lower()
    except (NatsError, TimeoutError):
        return False
    finally:
        await nc.close()


# The probes never change anything even where the permission exists: an empty stream configuration
# is refused by the server for its content, and the consumers deleted do not exist. Only a
# permission error counts as "not allowed"; any other answer means the request got through.


@pytest.mark.parametrize("user", sorted(USERS))
def test_a_service_user_cannot_create_or_change_a_stream(user: str) -> None:
    password, stream, _, _ = USERS[user]
    assert not asyncio.run(_allowed(user, password, "$JS.API.STREAM.CREATE.PROBE_ONLY"))
    assert not asyncio.run(_allowed(user, password, f"$JS.API.STREAM.UPDATE.{stream}"))


@pytest.mark.parametrize("user", sorted(USERS))
def test_a_service_user_reads_its_own_consumer_and_not_the_others(user: str) -> None:
    password, stream, durable, _ = USERS[user]
    assert asyncio.run(_allowed(user, password, f"$JS.API.CONSUMER.INFO.{stream}.{durable}"))
    others = [d for u, (_, s, d, _) in USERS.items() if u != user and s == stream]
    for other in others:
        assert not asyncio.run(_allowed(user, password, f"$JS.API.CONSUMER.INFO.{stream}.{other}"))
    assert not asyncio.run(
        _allowed(user, password, f"$JS.API.CONSUMER.DELETE.{stream}.probe-that-does-not-exist")
    )


def test_the_inventory_does_not_publish_campaign_events() -> None:
    async def attempt() -> bool:
        nc = await nats.connect(
            NATS_URL,
            tls=_tls(),
            tls_hostname="127.0.0.1",
            user="inventory",
            password="dev-only-nats-inventory",  # noqa: S106 - development password
            allow_reconnect=False,
            connect_timeout=5,
        )
        denied: list[str] = []

        async def on_error(exc: Exception) -> None:
            denied.append(str(exc))

        nc._error_cb = on_error  # noqa: SLF001 - the permission violation arrives as an async error
        try:
            js = nc.jetstream()
            try:
                await js.publish("argos.campaign.circuit_open", b"{}", timeout=2)
            except (NatsError, TimeoutError):
                return False
            return True
        finally:
            await nc.close()

    assert not asyncio.run(attempt())
