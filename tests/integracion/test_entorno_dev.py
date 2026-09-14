"""El entorno de make dev está vivo y tiene las extensiones que exige ARG-004."""

import os
import socket

import psycopg
import pytest

pytestmark = pytest.mark.integracion

DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")


def test_postgres_tiene_age_y_pgvector() -> None:
    with psycopg.connect(DSN) as conn:
        extensiones = {fila[0] for fila in conn.execute("SELECT extname FROM pg_extension")}
    assert {"age", "vector"} <= extensiones


@pytest.mark.parametrize(
    ("servicio", "puerto"),
    [
        ("nats", 4222),
        ("temporal", 7233),
        ("keycloak", 8180),
        ("vault", 8200),
        ("prometheus", 9090),
        ("loki", 3100),
        ("grafana", 3000),
        ("ejemplo", 8001),
    ],
)
def test_servicio_escucha(servicio: str, puerto: int) -> None:
    with socket.create_connection(("127.0.0.1", puerto), timeout=3):
        pass
