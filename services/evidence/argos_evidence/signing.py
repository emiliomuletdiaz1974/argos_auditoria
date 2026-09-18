"""Signature of a campaign's Merkle root (ARG-064, deviation note ARG-064-065).

The signed object says, in canonical JSON, everything the signature vouches
for: the Merkle root and how it was built, the campaign seal of Phase 05, the
head of the journal when the campaign was closed, when, with which algorithm
and which key. Changing any of it breaks the signature.

The key never leaves its custodian: a TPM in the appliance, the Vault transit
engine in development. A signer that does not declare itself ``production``
marks every object it signs as ``non_production``, so nothing signed on a
development bench can pass for evidence of an appliance.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from argos_common.errors import ArgosError
from argos_common.journal import canonicalize
from argos_common.journal_pg import PostgresJournal
from argos_common.release import Signer
from argos_evidence.artifacts import canonical_instant
from argos_evidence.journal import anchor_head
from argos_evidence.roots import get_root
from argos_evidence.worm import WormAlreadyStoredError, WormStore

SCHEMA = "argos/root-signature/1"
KIND = "campaign_root_signature"
ALGORITHM = "Ed25519"
ACTOR = "system:evidence"
JOURNAL_ACTION = "campaign.root_signed"
_HEX64 = re.compile(r"[0-9a-f]{64}")


class SigningError(ArgosError):
    """The campaign is not in a state that can be signed."""


@dataclass(frozen=True)
class SignatureRecord:
    campaign_id: str
    key: str
    version_id: str
    sha256: str
    key_id: str
    non_production: bool


def signature_key(campaign_id: str) -> str:
    return f"campaigns/{campaign_id}/root-signature.json"


def key_id(public_key: bytes) -> str:
    """Stable name of a key: the first 128 bits of the SHA-256 of its raw public bytes."""
    return hashlib.sha256(public_key).hexdigest()[:32]


def _is_production(signer: Signer) -> bool:
    return getattr(signer, "production", False) is True


def signing_payload(
    *,
    campaign_id: str,
    merkle_root: str,
    leaf_count: int,
    leaf_order: str,
    tree_key: str,
    campaign_seal: str,
    journal_head: Mapping[str, Any],
    signed_at: dt.datetime,
    signer: Signer,
) -> dict[str, Any]:
    """The canonical object the signature covers."""
    seq, entry_hash = journal_head.get("seq"), journal_head.get("entry_hash")
    if (
        not isinstance(seq, int)
        or not isinstance(entry_hash, str)
        or not _HEX64.fullmatch(entry_hash)
    ):
        raise ValueError("the journal head needs an integer seq and a SHA-256 entry_hash")
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "campaign_id": campaign_id,
        "merkle_root": merkle_root,
        "leaf_count": leaf_count,
        "leaf_order": leaf_order,
        "tree_key": tree_key,
        "campaign_seal": campaign_seal,
        "journal_head": {"seq": seq, "entry_hash": entry_hash},
        "signed_at": canonical_instant(signed_at),
        "algorithm": ALGORITHM,
        "key_id": key_id(signer.public_key()),
        "non_production": not _is_production(signer),
    }


def sign_payload(signer: Signer, payload: Mapping[str, Any]) -> dict[str, Any]:
    signature = signer.sign(canonicalize(dict(payload)).encode("utf-8"))
    return {
        "payload": dict(payload),
        "signature": signature.hex(),
        "public_key": signer.public_key().hex(),
    }


def envelope_bytes(envelope: Mapping[str, Any]) -> bytes:
    return canonicalize(dict(envelope)).encode("utf-8")


def verify_envelope(body: bytes, public_key: bytes) -> bool:
    """True when ``body`` is an envelope signed by ``public_key`` over its payload."""
    try:
        envelope = json.loads(body)
        payload = envelope["payload"]
        signature = bytes.fromhex(envelope["signature"])
        if payload.get("key_id") != key_id(public_key):
            return False
        data = canonicalize(payload).encode("utf-8")
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, data)
    except (ValueError, KeyError, TypeError, AttributeError, InvalidSignature):
        return False
    return True


def _signed(dsn: str, campaign_id: str) -> SignatureRecord | None:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT campaign_id::text, object_key, version_id, sha256, key_id, non_production"
            " FROM argos.campaign_signatures WHERE campaign_id = %s",
            (campaign_id,),
        ).fetchone()
    if row is None:
        return None
    return SignatureRecord(
        str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), bool(row[5])
    )


def _campaign_seal(dsn: str, campaign_id: str) -> str:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT status, seal FROM argos.campaigns WHERE id = %s", (campaign_id,)
        ).fetchone()
    if row is None:
        raise SigningError(f"campaign {campaign_id} does not exist")
    if row[0] != "sealed" or not row[1]:
        raise SigningError(
            f"campaign {campaign_id} is not sealed: only a closed campaign is signed"
        )
    return str(row[1])


def sign_campaign_root(
    dsn: str,
    store: WormStore,
    signer: Signer,
    campaign_id: str,
    journal_head: Mapping[str, Any] | None,
    retain_until: dt.datetime,
    now: dt.datetime | None = None,
) -> SignatureRecord:
    """Sign the root of a sealed campaign once, store the envelope and journal it.

    Without an explicit ``journal_head`` the current, verified head is anchored (ARG-066).
    """
    existing = _signed(dsn, campaign_id)
    if existing is not None:
        return existing
    seal = _campaign_seal(dsn, campaign_id)
    root = get_root(dsn, campaign_id)
    if root is None:
        raise SigningError(f"campaign {campaign_id} has no Merkle root to sign")

    if journal_head is None:
        journal_head = anchor_head(dsn)
    payload = signing_payload(
        campaign_id=campaign_id,
        merkle_root=root.root,
        leaf_count=root.leaf_count,
        leaf_order=root.leaf_order,
        tree_key=root.tree_key,
        campaign_seal=seal,
        journal_head=journal_head,
        signed_at=now or dt.datetime.now(dt.UTC),
        signer=signer,
    )
    body = envelope_bytes(sign_payload(signer, payload))
    key = signature_key(campaign_id)
    try:
        version_id = store.put_immutable(key, body, retain_until).version_id
    except WormAlreadyStoredError:
        # A previous attempt stored its envelope and stopped before indexing it: adopt it if it
        # is a valid signature of this root by this key.
        version_id = store.version_of(key)
        body = store.get(key, version_id)
        stored = json.loads(body)["payload"]
        if not verify_envelope(body, signer.public_key()) or stored["merkle_root"] != root.root:
            raise SigningError(f"{key} holds a signature this campaign cannot adopt") from None
        payload = stored

    digest = hashlib.sha256(body).hexdigest()
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO argos.campaign_signatures"
            " (campaign_id, object_key, version_id, sha256, key_id, non_production)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (campaign_id, key, version_id, digest, payload["key_id"], payload["non_production"]),
        )
        PostgresJournal(dsn).append(
            ACTOR,
            JOURNAL_ACTION,
            {
                "campaign": campaign_id,
                "merkle_root": root.root,
                "sha256": digest,
                "key_id": payload["key_id"],
                "non_production": payload["non_production"],
            },
            conn=conn,
        )
    record = _signed(dsn, campaign_id)
    if record is None:  # pragma: no cover - the insert above committed
        raise SigningError(f"the signature of {campaign_id} was not recorded")
    return record
