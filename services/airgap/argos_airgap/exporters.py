"""The exporters of the closed list: what may leave the appliance, and how it is written out.

- `tsq`: one query per object waiting for its time stamp (`export_requests`, ARG-065), named as
  its reply must come back (`tsr_name`), to be stamped by a TSA outside the appliance;
- `dossier`: the current dossier of a campaign in JSON and PDF, read from the WORM store and
  checked against the hash it was recorded with;
- `credential`: the verifiable credential of a campaign, checked the same way;
- `diagnostics`: the diagnostic package the operator reviewed (ARG-088), encrypted for support,
  only for the index the operator approved.
"""

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import psycopg

from argos_evidence.reads import current_dossier
from argos_evidence.tsa import export_requests
from argos_evidence.worm import WormStore
from argos_support import DiagnosticsStore, build_package

from .importers import tsr_name

Exporter = Callable[[Path, Mapping[str, str]], None]


def _campaign(params: Mapping[str, str]) -> str:
    try:
        return str(uuid.UUID(params.get("campaign_id", "")))
    except ValueError:
        raise ValueError("campaign_id must be the id of a campaign") from None


def _checked(store: WormStore, key: str, version_id: str, sha256: str) -> bytes:
    data = store.get(key, version_id)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f"{key} does not match the hash it was recorded with")
    return data


def tsq_exporter(dsn: str, store: WormStore) -> Exporter:
    def export(folder: Path, params: Mapping[str, str]) -> None:
        requests = export_requests(dsn, store)
        if not requests:
            raise LookupError("no object is waiting for its time stamp")
        for object_key, query in requests.items():
            (folder / tsr_name(object_key).replace(".tsr", ".tsq")).write_bytes(query)

    return export


def dossier_exporter(dsn: str, store: WormStore) -> Exporter:
    def export(folder: Path, params: Mapping[str, str]) -> None:
        campaign = _campaign(params)
        dossier = current_dossier(dsn, campaign)
        if dossier is None:
            raise LookupError(f"campaign {campaign} has no dossier yet")
        document = _checked(
            store, str(dossier["json_key"]), str(dossier["json_version_id"]), dossier["sha256"]
        )
        (folder / f"dossier-{campaign}.json").write_bytes(document)
        pdf = store.get(str(dossier["pdf_key"]), str(dossier["pdf_version_id"]))
        (folder / f"dossier-{campaign}.pdf").write_bytes(pdf)

    return export


def credential_exporter(dsn: str, store: WormStore) -> Exporter:
    def export(folder: Path, params: Mapping[str, str]) -> None:
        campaign = _campaign(params)
        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                "SELECT object_key, version_id, sha256 FROM argos.credentials"
                " WHERE campaign_id = %s ORDER BY issued_at DESC LIMIT 1",
                (campaign,),
            ).fetchone()
        if row is None:
            raise LookupError(f"campaign {campaign} has no credential")
        credential: Any = _checked(store, str(row[0]), str(row[1]), str(row[2]))
        json.loads(credential)  # it is the JSON that was issued, or the export stops here
        (folder / f"credential-{campaign}.json").write_bytes(credential)

    return export


def diagnostics_exporter(store: DiagnosticsStore, recipient: str) -> Exporter:
    def export(folder: Path, params: Mapping[str, str]) -> None:
        ident = params.get("diagnostics_id", "")
        preview = store.load(ident)
        package = build_package(preview, params.get("approved_index_sha256", ""), recipient)
        (folder / f"argos-diagnostics-{ident}.tar.gz.age").write_bytes(package)

    return export
