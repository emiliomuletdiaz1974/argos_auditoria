"""ARG-077 · evidence and credentials over the v1, shown as they are.

The chain is returned link by link with its real state: a signature made with a development key says
so, and a time stamp still in the queue says so too. Every artifact comes with its inclusion proof,
which verifies against the signed root. The dossier and the bundle are downloaded only with the
permission, and the journal keeps who downloaded what. Issuing a credential is an explicit act: the
preview shows exactly what will travel, and what is issued is that same content.
"""

import datetime as dt
from typing import cast

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app
from argos_auth import Identity, JwtValidator
from argos_common.release import VaultTransitSigner
from argos_evidence.activities import EvidenceActivities
from argos_evidence.merkle import verify_proof
from argos_evidence.settings import EvidenceSettings
from argos_evidence.tsa import http_transport, process_queue

from .test_dossier import TSA, VAULT, _campaign, _roots, _store

pytestmark = pytest.mark.integration


class PersonValidator:
    def validate(self, token: str) -> Identity:
        role, _, person = token.partition(":")
        return Identity(sub=person or role, name=person or role, roles=frozenset({role}))


def _as(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}:{role}"}


def _activities(dsn: str) -> EvidenceActivities:
    settings = EvidenceSettings(
        ISSUER_DID="did:web:evidence.argos.example",
        STATUS_BASE_URL="https://evidence.argos.example/status",
        CREDENTIAL_BASE_URL="https://evidence.argos.example/credentials",
        VERIFIER_URL="https://verify.argos.example/check",
        RETENTION_DAYS=1,
    )
    return EvidenceActivities(
        dsn,
        _store(),
        VaultTransitSigner(VAULT, "root", key="argos-evidence"),
        settings,
        http_transport(TSA),
        [httpx.get(f"{TSA}/ca.pem").text],
    )


@pytest.fixture
def evidence(migrated_db: str) -> EvidenceActivities:
    return _activities(migrated_db)


@pytest.fixture
def api(migrated_db: str, evidence: EvidenceActivities) -> TestClient:
    validator = cast(JwtValidator, PersonValidator())
    return TestClient(create_app(validator, dsn=migrated_db, evidence=evidence))


@pytest.fixture
def campaign(migrated_db: str) -> str:
    """Sealed, with its artifacts, its root signed with the development key and its stamp queued."""
    return _campaign(migrated_db, _store())


def _stamp(dsn: str) -> None:
    until = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10)
    process_queue(dsn, _store(), http_transport(TSA), _roots(), until)


def _downloads(dsn: str, campaign_id: str) -> list[tuple[str, str]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT actor, payload_canon FROM argos.audit_journal"
            " WHERE action = 'evidence.download' AND payload_canon LIKE %s ORDER BY seq",
            (f"%{campaign_id}%",),
        ).fetchall()
    return [(str(a), str(p)) for a, p in rows]


def test_the_chain_says_what_is_missing(api: TestClient, campaign: str) -> None:
    answer = api.get(f"{API_PREFIX}/evidence/{campaign}/chain", headers=_as("read_only_auditor"))
    assert answer.status_code == 200
    chain = answer.json()
    assert len(chain["artifacts"]) == 2
    assert chain["merkle"]["leaf_count"] == 2
    assert chain["signature"]["non_production"] is True, "a development key says so"
    assert chain["time_stamp"]["status"] == "queued", "a stamp still in the queue says so"
    assert chain["journal_report"] is not None


def test_once_stamped_the_chain_shows_the_policy(
    api: TestClient, campaign: str, migrated_db: str
) -> None:
    _stamp(migrated_db)
    chain = api.get(f"{API_PREFIX}/evidence/{campaign}/chain", headers=_as("dpo_reviewer")).json()
    assert chain["time_stamp"]["status"] == "stamped"
    assert chain["time_stamp"]["policy"]


def test_every_artifact_proves_its_place_in_the_signed_root(api: TestClient, campaign: str) -> None:
    page = api.get(
        f"{API_PREFIX}/evidence/{campaign}/artifacts",
        params={"limit": 1},
        headers=_as("dpo_reviewer"),
    )
    assert page.status_code == 200
    first = page.json()
    assert len(first["items"]) == 1 and first["next"]
    rest = api.get(
        f"{API_PREFIX}/evidence/{campaign}/artifacts",
        params={"limit": 1, "cursor": first["next"]},
        headers=_as("dpo_reviewer"),
    ).json()
    listed = [first["items"][0]["verdict_id"], rest["items"][0]["verdict_id"]]
    assert len(set(listed)) == 2

    for verdict_id in listed:
        detail = api.get(
            f"{API_PREFIX}/evidence/artifacts/{verdict_id}", headers=_as("read_only_auditor")
        ).json()
        proof = detail["proof"]
        path = [(side, bytes.fromhex(sibling)) for side, sibling in proof["path"]]
        assert verify_proof(
            bytes.fromhex(detail["sha256"]),
            proof["index"],
            proof["size"],
            path,
            bytes.fromhex(proof["root"]),
        )
        assert detail["artifact"]["verdict_id"] == verdict_id


def test_an_unknown_artifact_is_a_404(api: TestClient) -> None:
    answer = api.get(
        f"{API_PREFIX}/evidence/artifacts/00000000-0000-4000-8000-0000000000ff",
        headers=_as("dpo_reviewer"),
    )
    assert answer.status_code == 404


def test_without_a_dossier_there_is_nothing_to_download(api: TestClient, campaign: str) -> None:
    answer = api.get(f"{API_PREFIX}/evidence/{campaign}/dossier.json", headers=_as("dpo_reviewer"))
    assert answer.status_code == 404


def test_the_dossier_and_the_bundle_are_downloaded_and_the_journal_says_who(
    api: TestClient, campaign: str, migrated_db: str, evidence: EvidenceActivities
) -> None:
    _stamp(migrated_db)
    sha256 = evidence.write_dossier_now(campaign)
    evidence.issue_credential_now(campaign, sha256)

    as_json = api.get(f"{API_PREFIX}/evidence/{campaign}/dossier.json", headers=_as("dpo_reviewer"))
    assert as_json.status_code == 200
    assert as_json.headers["x-dossier-sha256"] == sha256
    assert as_json.json()["campaign"]["id"] == campaign

    as_pdf = api.get(f"{API_PREFIX}/evidence/{campaign}/dossier.pdf", headers=_as("dpo_reviewer"))
    assert as_pdf.status_code == 200
    assert as_pdf.headers["content-type"] == "application/pdf"
    assert as_pdf.content.startswith(b"%PDF")

    bundle = api.get(f"{API_PREFIX}/evidence/{campaign}/bundle", headers=_as("read_only_auditor"))
    assert bundle.status_code == 200
    assert bundle.json()["dossier"]

    downloads = _downloads(migrated_db, campaign)
    assert [actor for actor, _ in downloads] == [
        "user:dpo_reviewer",
        "user:dpo_reviewer",
        "user:read_only_auditor",
    ]
    assert all(sha256 in payload for _, payload in downloads)


def _dossier(evidence: EvidenceActivities, migrated_db: str, campaign: str) -> str:
    _stamp(migrated_db)
    return evidence.write_dossier_now(campaign)


def test_what_is_issued_is_what_the_preview_showed(
    api: TestClient, campaign: str, migrated_db: str, evidence: EvidenceActivities
) -> None:
    sha256 = _dossier(evidence, migrated_db, campaign)
    preview = api.get(
        f"{API_PREFIX}/credentials/preview",
        params={"campaign_id": campaign},
        headers=_as("dpo_reviewer"),
    )
    assert preview.status_code == 200
    shown = preview.json()
    assert shown["dossier_sha256"] == sha256

    issued = api.post(
        f"{API_PREFIX}/credentials",
        json={"campaign_id": campaign, "dossier_sha256": sha256},
        headers=_as("dpo_reviewer"),
    )
    assert issued.status_code == 201, issued.text
    credential = issued.json()["credential"]
    assert credential["credentialSubject"] == shown["credentialSubject"]
    assert credential["credentialSubject"]["nonProduction"] is True


def test_a_credential_is_not_issued_over_a_dossier_that_is_no_longer_current(
    api: TestClient, campaign: str, migrated_db: str, evidence: EvidenceActivities
) -> None:
    _dossier(evidence, migrated_db, campaign)
    stale = api.post(
        f"{API_PREFIX}/credentials",
        json={"campaign_id": campaign, "dossier_sha256": "0" * 64},
        headers=_as("dpo_reviewer"),
    )
    assert stale.status_code == 409


def test_issuing_is_for_the_dpo(api: TestClient, campaign: str) -> None:
    refused = api.post(
        f"{API_PREFIX}/credentials",
        json={"campaign_id": campaign, "dossier_sha256": "0" * 64},
        headers=_as("campaign_manager"),
    )
    assert refused.status_code == 403


def test_a_revoked_credential_says_so(
    api: TestClient, campaign: str, migrated_db: str, evidence: EvidenceActivities
) -> None:
    sha256 = _dossier(evidence, migrated_db, campaign)
    issued = api.post(
        f"{API_PREFIX}/credentials",
        json={"campaign_id": campaign, "dossier_sha256": sha256},
        headers=_as("dpo_reviewer"),
    ).json()
    credential_id = issued["credential_id"]

    alive = api.get(f"{API_PREFIX}/credentials/{credential_id}", headers=_as("read_only_auditor"))
    assert alive.json()["revoked"] is False

    no_reason = api.post(
        f"{API_PREFIX}/credentials/{credential_id}/revoke",
        json={"reason": ""},
        headers=_as("platform_admin"),
    )
    assert no_reason.status_code == 422
    revoked = api.post(
        f"{API_PREFIX}/credentials/{credential_id}/revoke",
        json={"reason": "expediente sustituido por error de alcance"},
        headers=_as("platform_admin"),
    )
    assert revoked.status_code == 200
    after = api.get(f"{API_PREFIX}/credentials/{credential_id}", headers=_as("read_only_auditor"))
    assert after.json()["revoked"] is True
    assert after.json()["revocation"]["reason"] == "expediente sustituido por error de alcance"


def test_without_the_evidence_service_the_routes_say_so(migrated_db: str, campaign: str) -> None:
    validator = cast(JwtValidator, PersonValidator())
    client = TestClient(create_app(validator, dsn=migrated_db))
    answer = client.get(f"{API_PREFIX}/evidence/{campaign}/chain", headers=_as("dpo_reviewer"))
    assert answer.status_code == 503
