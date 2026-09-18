"""ARG-070 · the EDC client: only credentials travel, under a policy ARGOS can read back."""

import json
from typing import Any

import httpx
import pytest

from argos_evidence.dataspace.edc import (
    POLICY_LIBRARY,
    EdcClient,
    EdcError,
    asset_id_for,
    build_policy,
)
from argos_ontology.odrl import parse_policy

CREDENTIAL: dict[str, Any] = {
    "@context": ["https://www.w3.org/ns/credentials/v2"],
    "id": "urn:uuid:0199a000-0000-7000-8000-00000000000c",
    "type": ["VerifiableCredential", "ArgosCampaignCredential"],
    "issuer": "did:web:evidence.argos.example",
    "credentialSubject": {
        "campaignId": "0199a000-0000-7000-8000-000000000001",
        "dossierSha256": "d" * 64,
    },
    "proof": {"type": "DataIntegrityProof"},
}
URL = "https://evidence.argos.example/credentials/0199a000"


def _client(sent: list[httpx.Request], status: int = 200) -> EdcClient:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(status, json={"@id": json.loads(request.content)["@id"]})

    return EdcClient(
        "http://edc.test/management",
        "key-for-tests",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("choice", sorted(POLICY_LIBRARY))
def test_every_library_policy_reads_back_with_nothing_unverifiable(choice: str) -> None:
    policy = build_policy("asset-1", choice)
    parsed = parse_policy(policy)
    assert parsed.target == "asset-1"
    assert parsed.unsupported == ()


def test_an_unknown_choice_is_refused() -> None:
    with pytest.raises(EdcError, match="policy"):
        build_policy("asset-1", "anything-goes")


def test_publishing_sends_asset_policy_and_contract_with_the_key() -> None:
    sent: list[httpx.Request] = []
    record = _client(sent).publish_credential(CREDENTIAL, URL, "no_redistribution")
    paths = [r.url.path for r in sent]
    assert paths == [
        "/management/v3/assets",
        "/management/v3/policydefinitions",
        "/management/v3/contractdefinitions",
    ]
    assert all(r.headers["x-api-key"] == "key-for-tests" for r in sent)
    asset, policy, contract = (json.loads(r.content) for r in sent)
    assert asset["@id"] == record.asset_id == asset_id_for(CREDENTIAL)
    assert asset["dataAddress"]["baseUrl"] == URL
    assert asset["properties"]["contenttype"] == "application/vc+json"
    assert parse_policy(policy["policy"]).unsupported == ()
    assert contract["accessPolicyId"] == contract["contractPolicyId"] == policy["@id"]
    assert contract["assetsSelector"][0]["operandRight"] == record.asset_id


def test_an_already_published_credential_is_not_an_error() -> None:
    sent: list[httpx.Request] = []
    record = _client(sent, status=409).publish_credential(CREDENTIAL, URL, "use_only")
    assert record.asset_id == asset_id_for(CREDENTIAL)


def test_a_rejected_request_stops_the_publication() -> None:
    sent: list[httpx.Request] = []
    with pytest.raises(EdcError, match="401"):
        _client(sent, status=401).publish_credential(CREDENTIAL, URL, "use_only")
    assert len(sent) == 1


def test_only_a_campaign_credential_can_travel() -> None:
    sent: list[httpx.Request] = []
    dossier = {"schema": "argos/dossier/1", "campaign": {}, "sha256": "e" * 64}
    for document in (dossier, {**CREDENTIAL, "type": ["VerifiableCredential"]}):
        with pytest.raises(EdcError, match="credential"):
            _client(sent).publish_credential(document, URL, "use_only")
    unsigned = {k: v for k, v in CREDENTIAL.items() if k != "proof"}
    with pytest.raises(EdcError, match="signed"):
        _client(sent).publish_credential(unsigned, URL, "use_only")
    assert sent == []
