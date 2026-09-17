"""ARG-052 · the AI role cannot write a verdict, whatever the code says (F06-01).

The static barrier (`tests/architecture/test_ai_boundary.py`) checks the source tree. This one
checks the database: even if somebody found a way around the code, the role the gateway connects
with has no privilege to touch a verdict or a finding. The third half, the network, lives in
`tests/integration/test_ai_containers.py` (F06-13).
"""

import psycopg
import pytest

pytestmark = pytest.mark.integration

AI_ROLE = "argos_ai"
WRITES = (
    "INSERT INTO argos.verdicts (id, campaign_id, unit_id, challenge_id, challenge_version, "
    "obligation, system_id, node_key, result, verdict, verdict_hash) "
    "VALUES (gen_random_uuid(), gen_random_uuid(), 'u', 'c', '1.0', 'o', gen_random_uuid(), "
    "'n', 'compliant', '{}'::jsonb, 'h')",
    "UPDATE argos.verdicts SET result = 'compliant'",
    "DELETE FROM argos.verdicts",
    "UPDATE argos.findings SET status = 'closed_compliant'",
    "DELETE FROM argos.findings",
)
READS = (
    "SELECT count(*) FROM argos.verdicts",
    "SELECT count(*) FROM argos.findings",
    "SELECT count(*) FROM argos.campaigns",
)


def _as_ai(dsn: str) -> psycopg.Connection:
    """A connection with the privileges of the AI role, on the same database."""
    connection = psycopg.connect(dsn)
    connection.execute(f"SET ROLE {AI_ROLE}")
    return connection


def test_the_ai_role_exists_after_the_migrations(migrated_db: str) -> None:
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", (AI_ROLE,)
        ).fetchone()
    assert row is not None, f"the migrations did not create the role {AI_ROLE}"


@pytest.mark.parametrize("statement", WRITES)
def test_the_ai_role_cannot_touch_a_verdict_or_a_finding(migrated_db: str, statement: str) -> None:
    with _as_ai(migrated_db) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)


@pytest.mark.parametrize("statement", READS)
def test_the_ai_role_may_read_what_it_has_to_narrate(migrated_db: str, statement: str) -> None:
    """ARG-057 writes the report from the verdicts: reading them is its job."""
    with _as_ai(migrated_db) as conn:
        assert conn.execute(statement).fetchone() is not None


def test_the_ai_role_owns_its_own_tables(migrated_db: str) -> None:
    """What belongs to the gateway it may write: its usage log is its own."""
    with _as_ai(migrated_db) as conn:
        conn.execute(
            "INSERT INTO argos.ai_usage (service, model, prompt_sha256, tokens_in, tokens_out) "
            "VALUES ('reports', 'fake', %s, 10, 20)",
            ("a" * 64,),
        )
        assert conn.execute("SELECT count(*) FROM argos.ai_usage").fetchone() == (1,)
