"""ARG-085 (base) · one PostgreSQL role per service, with the least privilege (F09-04).

The expectation is `tests/fixtures/db_access_matrix.yaml`, written from the access inventory of each
service; this test asks the database what every role may do and compares. A second test logs in as
a user that is only a member of a service role and does real work with it: reads the graph, writes
the journal through its function, and is refused a rewrite.
"""

import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
import yaml
from psycopg import sql

pytestmark = pytest.mark.integration

MATRIX = Path(__file__).resolve().parents[1] / "fixtures" / "db_access_matrix.yaml"
CASES = yaml.safe_load(MATRIX.read_text(encoding="utf-8"))["cases"]
SERVICE_ROLES = (
    "svc_inventory",
    "svc_ontology",
    "svc_challenge",
    "svc_evidence",
    "svc_api",
    "svc_ai_gateway",
    "svc_webhook",
    "svc_example",
    "svc_migrator",
)


def _allowed(conn: psycopg.Connection, role: str, target: str, privilege: str) -> bool:
    grantee = "public" if role == "PUBLIC" else role
    if target.endswith("()"):
        row = conn.execute(
            "SELECT bool_or(has_function_privilege(%s, p.oid, %s)) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'argos' AND p.proname = %s",
            (grantee, privilege, target[:-2]),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT has_table_privilege(%s, %s, %s)", (grantee, f"argos.{target}", privilege)
        ).fetchone()
    assert row is not None and row[0] is not None, (role, target)
    return bool(row[0])


@pytest.mark.parametrize(("role", "target", "privilege", "expected"), CASES)
def test_each_role_may_do_exactly_what_the_matrix_says(
    migrated_db: str, role: str, target: str, privilege: str, expected: bool
) -> None:
    with psycopg.connect(migrated_db) as conn:
        assert _allowed(conn, role, target, privilege) is expected


def test_the_service_roles_exist_and_nobody_logs_in_with_them(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        rows = dict(
            conn.execute(
                "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = ANY(%s)",
                (list(SERVICE_ROLES),),
            ).fetchall()
        )
    assert set(rows) == set(SERVICE_ROLES)
    assert not any(rows.values()), "service roles are NOLOGIN: people log in as their members"


@pytest.fixture
def gateway_user(migrated_db: str) -> Iterator[str]:
    """A login user that is only a member of svc_ai_gateway, as F09-05 will create them."""
    name, password = f"probe_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE svc_ai_gateway").format(
                sql.Identifier(name), sql.Literal(password)
            )
        )
    host = migrated_db.split("@", 1)[1]
    try:
        yield f"postgresql://{name}:{password}@{host}"
    finally:
        with psycopg.connect(migrated_db, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


def test_a_member_of_a_service_role_works_and_is_refused_what_is_not_its(
    gateway_user: str,
) -> None:
    with psycopg.connect(gateway_user, autocommit=True) as conn:
        conn.execute("SET search_path = ag_catalog, public")  # AGE is preloaded: no LOAD needed
        conn.execute(
            "SELECT * FROM cypher('inventory', $$ MATCH (n:System) RETURN count(n) $$)"
            " AS (n agtype)"
        )
        seq = conn.execute(
            "SELECT argos.journal_append('user:probe', 'probe.role', '{}')"
        ).fetchone()
        assert seq is not None
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE argos.audit_journal SET actor = 'x'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT 1 FROM argos.synthetic_subjects LIMIT 1")


# Every container of ARGOS that reaches the database, and the login user it must arrive as.
CONTAINERS = {
    "example": "login_example",
    "challenge-worker": "login_challenge",
    "api": "login_api",
    "webhook-worker": "login_webhook",
    "evidence-worker": "login_evidence",
    "evidence-api": "login_evidence",
    "ai-gateway": "login_ai_gateway",
}
COMPOSE = [
    "docker",
    "compose",
    "-f",
    str(Path(__file__).resolve().parents[2] / "deploy/dev/compose.yaml"),
]
WHO = (
    "import psycopg\n"
    "from argos_common.config import get_config\n"
    "with psycopg.connect(get_config().DATABASE_URL) as conn:\n"
    "    print(*conn.execute('SELECT current_user, rolsuper FROM pg_roles"
    " WHERE rolname = current_user').fetchone())\n"
)


@pytest.mark.parametrize(("container", "user"), sorted(CONTAINERS.items()))
def test_each_container_connects_as_its_own_user_and_never_as_the_superuser(
    container: str, user: str
) -> None:
    probe = subprocess.run(  # noqa: S603 - fixed command against the development environment
        [*COMPOSE, "exec", "-T", container, "/app/.venv/bin/python", "-c", WHO],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.split() == [user, "False"]


def test_nobody_connects_over_the_network_without_a_password(migrated_db: str) -> None:
    host = migrated_db.split("@", 1)[1]
    with pytest.raises(psycopg.OperationalError, match="password"):
        psycopg.connect(f"postgresql://argos@{host}", password="", connect_timeout=5)
