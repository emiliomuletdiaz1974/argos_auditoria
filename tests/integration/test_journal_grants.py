"""ARG-005 · the journal admits from each role only its own entries, and only in canonical form.

Security review F09-02, SEC-017: `journal_append` took any actor and any action from any role that
could execute it, the AI gateway included, and stored the text it was given without checking that
it was canonical. A payload with a duplicated key hashed one thing and was read as another.

Each service role now writes with the actors and actions of `argos.journal_grants`, and the engine
rebuilds the canonical text of ADR-0002 from the payload and refuses what differs. The hash of the
chain does not change: the journal v1 is the same journal.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql

from argos_common.journal import canonicalize

pytestmark = pytest.mark.integration


def _member_of(migrated_db: str, role: str) -> Iterator[str]:
    name, password = f"probe_{uuid.uuid4().hex[:8]}", uuid.uuid4().hex
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier(role)
            )
        )
    host = migrated_db.split("@", 1)[1]
    try:
        yield f"postgresql://{name}:{password}@{host}"
    finally:
        with psycopg.connect(migrated_db, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


@pytest.fixture
def gateway(migrated_db: str) -> Iterator[str]:
    yield from _member_of(migrated_db, "svc_ai_gateway")


@pytest.fixture
def evidence(migrated_db: str) -> Iterator[str]:
    yield from _member_of(migrated_db, "svc_evidence")


@pytest.fixture
def api(migrated_db: str) -> Iterator[str]:
    yield from _member_of(migrated_db, "svc_api")


def _append(dsn: str, actor: str, action: str, canon: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT argos.journal_append(%s, %s, %s)", (actor, action, canon)
        ).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize(
    ("actor", "action"),
    [
        ("user:dpo", "ai.completion"),  # a person, from the gateway
        ("system:ai-gateway", "campaign.seal"),  # its own name, somebody else's act
        ("system:campaign", "ai.completion"),  # somebody else's name
        ("system:ai-gateway-x", "ai.completion"),  # its name as a prefix is not its name
    ],
)
def test_the_gateway_writes_only_as_itself_and_only_its_acts(
    gateway: str, actor: str, action: str
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _append(gateway, actor, action, "{}")


def test_the_gateway_still_writes_what_is_its_own(gateway: str) -> None:
    assert _append(gateway, "system:ai-gateway", "ai.completion", '{"prompt_sha256":"x"}') > 0


def test_the_evidence_service_does_not_speak_for_a_person(evidence: str) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _append(evidence, "user:dpo", "credential.issued", "{}")
    assert _append(evidence, "system:evidence", "credential.issued", "{}") > 0


def test_the_api_writes_what_a_person_did(api: str) -> None:
    assert _append(api, "user:dpo", "api.mutation", '{"method":"POST"}') > 0


@pytest.mark.parametrize(
    "canon",
    [
        '{"a":1,"a":2}',  # a duplicated key: the hash says one thing, jsonb keeps another
        '{"a": 1}',  # whitespace
        '{"b":1,"a":2}',  # unsorted keys
        '{"a":1.5}',  # a floating point number is never canonical
        '{"a":1.0}',
        '{"a":"\\u00e9"}',  # an escaped character that the canonical form writes as it is
        "[1,2]",  # not an object
    ],
)
def test_a_payload_that_is_not_canonical_is_refused(migrated_db: str, canon: str) -> None:
    with pytest.raises(psycopg.errors.RaiseException, match="canonical"):
        _append(migrated_db, "system:probe", "probe.canon", canon)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"z": 1, "a": [], "m": {}},
        {"é": "ñ", "e": "z", "E": "Z", "ß": "𝄞"},  # order by code point, not by collation
        {"text": 'comillas " barra \\ y /'},
        {"control": "\n\r\t\b\f\u0001\u001f\u007f"},
        {"nested": {"b": [1, -2, 0, 12345678901234567890], "a": [True, False, None]}},
        {"line separators": "  "},
    ],
)
def test_what_the_client_canonicalizes_the_engine_accepts(
    migrated_db: str, payload: dict[str, Any]
) -> None:
    canon = canonicalize(payload)
    seq = _append(migrated_db, "system:probe", "probe.canon", canon)
    with psycopg.connect(migrated_db) as conn:
        row = conn.execute(
            "SELECT payload_canon FROM argos.audit_journal WHERE seq = %s", (seq,)
        ).fetchone()
    assert row is not None and row[0] == canon
