"""Publication of campaign credentials in data spaces through an EDC connector (ARG-070).

The credential, and only the credential, becomes an asset of the Eclipse
Dataspace Connector with an ODRL policy and a contract definition, through its
Management API. The dossier never travels this way: it stays with the client,
and the credential points to it by its hash.

Every policy ARGOS attaches is one ARGOS can read back and verify: it is built
from a closed library and checked with the same parser that reads the policies
received from data spaces (ARG-035). A policy with a clause that parser marks
as not verifiable is refused before anything is sent; that is why "attribution"
is not in the library.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg

from argos_common.errors import ArgosError
from argos_common.journal_pg import PostgresJournal
from argos_ontology.odrl import PolicyError, parse_policy

EDC_CONTEXT = {
    "@vocab": "https://w3id.org/edc/v0.0.1/ns/",
    "odrl": "http://www.w3.org/ns/odrl/2/",
}
ODRL_CONTEXT = "http://www.w3.org/ns/odrl.jsonld"
CREDENTIAL_TYPE = "ArgosCampaignCredential"
ACCEPTED = {200, 204}
ALREADY_THERE = 409
POLICY_LIBRARY = {
    "use_only": "Use, with no further condition",
    "no_redistribution": "Use, and redistribution is prohibited",
    "retention": "Use, and delete after the retention term",
}


class EdcError(ArgosError):
    """The credential cannot be published as asked."""


@dataclass(frozen=True)
class PublishRecord:
    asset_id: str
    policy_id: str
    contract_id: str
    policy_choice: str


def asset_id_for(credential: Mapping[str, Any]) -> str:
    return "argos-credential-" + str(credential["id"]).removeprefix("urn:uuid:")


def build_policy(asset_id: str, choice: str, retention_days: int = 365) -> dict[str, Any]:
    """An ODRL Set from the closed library, checked by the ARG-035 parser."""
    if choice not in POLICY_LIBRARY:
        raise EdcError(f"no policy {choice!r} in the library: {', '.join(sorted(POLICY_LIBRARY))}")
    policy: dict[str, Any] = {
        "@context": ODRL_CONTEXT,
        "@type": "Set",
        "uid": f"urn:argos:policy:{asset_id}:{choice}",
        "target": asset_id,
        "permission": [{"action": "use", "target": asset_id}],
    }
    if choice == "no_redistribution":
        policy["prohibition"] = [{"action": "distribute", "target": asset_id}]
    if choice == "retention":
        if retention_days < 1:
            raise EdcError("the retention term is at least one day")
        policy["obligation"] = [
            {
                "action": "delete",
                "target": asset_id,
                "constraint": [
                    {
                        "leftOperand": "elapsedTime",
                        "operator": "lteq",
                        "rightOperand": f"P{retention_days}D",
                    }
                ],
            }
        ]
    try:
        parsed = parse_policy(policy)
    except PolicyError as exc:  # pragma: no cover - the library is built to parse
        raise EdcError(f"the policy {choice!r} does not parse: {exc}") from exc
    if parsed.unsupported:
        raise EdcError(
            f"the policy {choice!r} has clauses ARGOS cannot verify: {parsed.unsupported}"
        )
    return policy


def _check_publishable(document: Mapping[str, Any]) -> None:
    types = document.get("type") or []
    subject = document.get("credentialSubject") or {}
    if (
        "schema" in document
        or "VerifiableCredential" not in types
        or CREDENTIAL_TYPE not in types
        or "dossierSha256" not in subject
    ):
        raise EdcError("only a campaign credential is published in a data space, never a dossier")
    if "proof" not in document:
        raise EdcError("only a signed credential is published")


class EdcClient:
    """Client of the EDC Management API (v3)."""

    def __init__(self, management_url: str, api_key: str, http: httpx.Client | None = None) -> None:
        self._base = management_url.rstrip("/")
        self._key = api_key
        self._http = http or httpx.Client(timeout=30)

    def _post(self, path: str, body: Mapping[str, Any]) -> None:
        response = self._http.post(
            f"{self._base}{path}", json=dict(body), headers={"x-api-key": self._key}
        )
        if response.status_code not in ACCEPTED and response.status_code != ALREADY_THERE:
            raise EdcError(f"the EDC answered {response.status_code} to {path}")

    def publish_credential(
        self,
        credential: Mapping[str, Any],
        credential_url: str,
        choice: str,
        retention_days: int = 365,
    ) -> PublishRecord:
        """Publish a signed campaign credential as an asset under a library policy."""
        _check_publishable(credential)
        asset_id = asset_id_for(credential)
        policy = build_policy(asset_id, choice, retention_days)
        policy_id = f"pol-{asset_id}-{choice}"
        contract_id = f"cd-{asset_id}-{choice}"
        self._post(
            "/v3/assets",
            {
                "@context": EDC_CONTEXT,
                "@id": asset_id,
                "properties": {
                    "name": f"ARGOS campaign credential {credential['id']}",
                    "contenttype": "application/vc+json",
                    "dossierSha256": credential["credentialSubject"]["dossierSha256"],
                },
                "dataAddress": {"type": "HttpData", "baseUrl": credential_url},
            },
        )
        self._post(
            "/v3/policydefinitions",
            {"@context": EDC_CONTEXT, "@id": policy_id, "policy": policy},
        )
        self._post(
            "/v3/contractdefinitions",
            {
                "@context": EDC_CONTEXT,
                "@id": contract_id,
                "accessPolicyId": policy_id,
                "contractPolicyId": policy_id,
                "assetsSelector": [
                    {
                        "@type": "Criterion",
                        "operandLeft": "https://w3id.org/edc/v0.0.1/ns/id",
                        "operator": "=",
                        "operandRight": asset_id,
                    }
                ],
            },
        )
        return PublishRecord(asset_id, policy_id, contract_id, choice)


def record_publication(dsn: str, credential_id: str, record: PublishRecord, by: str) -> None:
    """Keep, once, that this credential was published and under which policy."""
    with psycopg.connect(dsn) as conn:
        inserted = conn.execute(
            "INSERT INTO argos.dataspace_publications"
            " (credential_id, asset_id, policy_id, contract_id, policy_choice, published_by)"
            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (credential_id, asset_id) DO NOTHING"
            " RETURNING credential_id",
            (
                credential_id,
                record.asset_id,
                record.policy_id,
                record.contract_id,
                record.policy_choice,
                by,
            ),
        ).fetchone()
        if inserted is not None:
            PostgresJournal(dsn).append(
                by,
                "credential.published",
                {
                    "credential": credential_id,
                    "asset": record.asset_id,
                    "policy": record.policy_choice,
                },
                conn=conn,
            )
