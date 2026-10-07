"""QA-36 · the remediation run works as the worker's own role, not only as a superuser.

The tests of the remediation connect as the owner, and the journal exempts a superuser from its
grants. In the bench the worker is `svc_challenge`, which writes only `system:%`: a remediation
campaign journalled as the person who asked was refused, the API answered 200 and the finding
stayed in `pending_verification`.
"""

import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql

from argos_challenges.activities import ChallengeActivities

from .inventory_helpers import secret_store
from .test_remediation import MANAGER, pending  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration


@pytest.fixture
def worker_dsn(migrated_db: str) -> Iterator[str]:
    """A login user that is only a member of svc_challenge, as the credentials service makes it."""
    name, password = f"worker_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE svc_challenge").format(
                sql.Identifier(name), sql.Literal(password)
            )
        )
    host = migrated_db.split("@", 1)[1]
    try:
        yield f"postgresql://{name}:{password}@{host}"
    finally:
        with psycopg.connect(migrated_db, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(name)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


def test_the_remediation_campaign_is_created_by_the_worker_role(
    migrated_db: str,
    worker_dsn: str,
    pending: tuple[str, dict[str, str]],  # noqa: F811
) -> None:
    origin, _ = pending
    activities = ChallengeActivities(worker_dsn, secret_store())
    started = activities._start_remediation({"campaign_id": origin, "requested_by": MANAGER})
    assert started["units"], "the units awaiting verification are re-run"
    with psycopg.connect(migrated_db) as conn:
        owner = conn.execute(
            "SELECT created_by FROM argos.campaigns WHERE id = %s", (started["campaign_id"],)
        ).fetchone()
        entry = conn.execute(
            "SELECT actor, payload FROM argos.audit_journal WHERE action = 'campaign.create'"
            " AND payload->>'campaign' = %s",
            (started["campaign_id"],),
        ).fetchone()
    # Whoever asked is still the creator, so they cannot approve what they asked for (SEC-008);
    # the journal records the system acting and, in the entry, the person it acted for.
    assert owner == (MANAGER,)
    assert entry is not None
    assert entry[0] == "system:remediation"
    assert entry[1]["requested_by"] == MANAGER


def test_the_worker_role_can_expire_an_accepted_risk(migrated_db: str, worker_dsn: str) -> None:
    from datetime import date, timedelta

    from argos_challenges.findings import expire_risk_acceptances

    with psycopg.connect(migrated_db) as conn:
        conn.execute(
            "INSERT INTO argos.campaigns (id, name, scope, created_by) VALUES "
            "('00000000-0000-4000-8000-0000000000c1', 'x', '{}', 'user:m')"
        )
        conn.execute(
            "INSERT INTO argos.findings (id, fingerprint, campaign_id, challenge_id, obligation,"
            " system_id,"
            " node_key, severity, status, risk_note, risk_expiry) VALUES "
            "('00000000-0000-4000-8000-0000000000f1', 'fp1',"
            " '00000000-0000-4000-8000-0000000000c1',"
            " 'c', 'OBL-RGPD-32-3', '00000000-0000-4000-8000-000000000001', 'k', 'high',"
            " 'risk_accepted', 'ok', %s)",
            (date.today() - timedelta(days=1),),
        )
    assert expire_risk_acceptances(worker_dsn) == ["00000000-0000-4000-8000-0000000000f1"]
