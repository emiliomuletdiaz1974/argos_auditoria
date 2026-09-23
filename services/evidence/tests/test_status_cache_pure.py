"""SEC-056 · the public status endpoint does not make the signer work on every request."""

from typing import Any, cast

import pytest

from argos_evidence import activities as module
from argos_evidence.activities import EvidenceActivities
from argos_evidence.settings import EvidenceSettings


class Settings:
    ISSUER_DID = "did:web:evidence.argos.example"
    STATUS_BASE_URL = "https://evidence.argos.example/status"


def _activities(monkeypatch: pytest.MonkeyPatch, revoked: list[tuple[int, ...]]) -> list[int]:
    signed: list[int] = []

    def sign(*args: Any, **kwargs: Any) -> dict[str, Any]:
        signed.append(args[4])
        return {"id": f"list-{args[4]}", "signed": len(signed)}

    monkeypatch.setattr(module, "revoked_indices", lambda dsn, number: revoked[0])
    monkeypatch.setattr(module, "status_list_credential", sign)
    return signed


def _make() -> EvidenceActivities:
    return EvidenceActivities(
        "postgresql://unused",
        cast(Any, None),
        cast(Any, None),
        cast(EvidenceSettings, Settings()),
        cast(Any, None),
        [],
    )


def test_the_same_list_is_served_without_signing_again(monkeypatch: pytest.MonkeyPatch) -> None:
    signed = _activities(monkeypatch, [()])
    activities = _make()
    first = activities.status_list(0)
    for _ in range(50):
        assert activities.status_list(0) == first
    assert signed == [0]


def test_a_revocation_signs_a_new_list_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    revoked: list[tuple[int, ...]] = [()]
    signed = _activities(monkeypatch, revoked)
    activities = _make()
    before = activities.status_list(0)
    revoked[0] = (7,)
    after = activities.status_list(0)
    assert before != after
    assert signed == [0, 0]
