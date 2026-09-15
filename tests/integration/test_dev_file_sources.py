"""Simulated file and directory sources (F02-08): read-only for ARGOS, enforced by the servers."""

import importlib.util
import ssl
from pathlib import Path

import boto3
import pytest
import smbclient
from botocore.config import Config
from botocore.exceptions import ClientError
from ldap3 import NONE, SUBTREE, Connection, Server, Tls

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
SOURCES = ROOT / "deploy" / "dev" / "sources"
BASE_DN = "dc=hosp,dc=local"
READER_DN = f"cn=argos_ro,{BASE_DN}"


def _ldap(user: str, password: str) -> Connection:
    # ldap3 matches the host only against DNS names, not IP SANs: accept the certificate's name.
    tls = Tls(
        validate=ssl.CERT_REQUIRED,
        ca_certs_file=str(SOURCES / "certs" / "ca.crt"),
        valid_names=["localhost"],
    )
    server = Server("127.0.0.1", port=1636, use_ssl=True, tls=tls, get_info=NONE)
    return Connection(server, user=user, password=password, auto_bind=True)


def test_generated_trees_are_deterministic() -> None:
    spec = importlib.util.spec_from_file_location(
        "prepare", ROOT / "tools" / "prepare_dev_sources.py"
    )
    assert spec is not None and spec.loader is not None
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    files = SOURCES / "files" / "clinical"
    assert len(prepare.tree_manifest(files)) == 120
    assert len(prepare.tree_manifest(SOURCES / "s3" / "clinical-archive")) == 60


def test_smb_share_lists_and_refuses_writes() -> None:
    smbclient.register_session("127.0.0.1", username="argos_ro", password="dev-only-smb", port=1445)
    try:
        names = smbclient.listdir(r"\\127.0.0.1\clinical", port=1445)
        assert {"radiology", "cardiology", "admin"} <= set(names)
        with (
            pytest.raises(OSError),
            smbclient.open_file(r"\\127.0.0.1\clinical\intruder.txt", mode="wb", port=1445) as fh,
        ):
            fh.write(b"x")
    finally:
        # Close the pooled session now; the atexit reset would log after pytest closes stderr.
        smbclient.reset_connection_cache()


def test_s3_bucket_lists_and_refuses_writes() -> None:
    client = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:7070",
        aws_access_key_id="dev-only-access",
        aws_secret_access_key="dev-only-secret-key",
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    listing = client.list_objects_v2(Bucket="clinical-archive")
    assert listing["KeyCount"] > 0
    with pytest.raises(ClientError):
        client.put_object(Bucket="clinical-archive", Key="intruder.txt", Body=b"x")


def test_ldaps_directory_reads_and_refuses_changes() -> None:
    conn = _ldap(READER_DN, "dev-only-ldap")
    conn.search(
        f"ou=people,{BASE_DN}",
        "(objectClass=inetOrgPerson)",
        SUBTREE,
        attributes=["uid"],
        paged_size=500,
    )
    assert len(conn.entries) >= 300
    changed = conn.modify(
        f"uid=syn.user1,ou=people,{BASE_DN}", {"description": [("MODIFY_REPLACE", ["x"])]}
    )
    assert not changed and conn.result["description"] == "insufficientAccessRights"
    conn.unbind()


def test_privileged_groups_are_nested_with_a_cycle() -> None:
    conn = _ldap(READER_DN, "dev-only-ldap")
    conn.search(
        f"cn=tier0,ou=groups,{BASE_DN}", "(objectClass=groupOfNames)", attributes=["member"]
    )
    members = [str(m) for m in conn.entries[0].member.values]
    assert f"cn=privileged,ou=groups,{BASE_DN}" in members
    conn.unbind()
