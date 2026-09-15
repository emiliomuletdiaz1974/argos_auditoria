"""The make dev environment is up and has the extensions required by ARG-004."""

import os
import socket

import psycopg
import pytest

pytestmark = pytest.mark.integration

DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")


def test_postgres_has_age_and_pgvector() -> None:
    with psycopg.connect(DSN) as conn:
        extensions = {row[0] for row in conn.execute("SELECT extname FROM pg_extension")}
    assert {"age", "vector"} <= extensions


@pytest.mark.parametrize(
    ("service", "port"),
    [
        ("nats", 4222),
        ("temporal", 7233),
        ("keycloak", 8180),
        ("vault", 8200),
        ("prometheus", 9090),
        ("loki", 3100),
        ("grafana", 3000),
        ("example", 8001),
        ("source-postgres", 55433),
        ("source-mariadb", 53306),
        ("source-smb", 1445),
        ("source-s3", 7070),
        ("source-ldap", 1636),
        ("source-fhir", 8090),
        ("source-dicom", 4242),
        ("source-dicom-rest", 8042),
    ],
)
def test_service_is_listening(service: str, port: int) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=3):
        pass
