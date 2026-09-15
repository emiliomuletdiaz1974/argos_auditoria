"""ARG-017 · file connector against the simulated local, SMB and S3 sources."""

import importlib.util
from pathlib import Path

import psycopg
import pytest

from argos_connector.probes import ProbeSpec
from argos_files.connector import FilesConnector

from .sources import ROOT, open_source_connector

pytestmark = pytest.mark.integration

_spec = importlib.util.spec_from_file_location("prepare", ROOT / "tools" / "prepare_dev_sources.py")
assert _spec is not None and _spec.loader is not None
prepare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prepare)

TREES = {
    "dev-files-local": ROOT / "deploy" / "dev" / "sources" / "files" / "clinical",
    "dev-files-smb": ROOT / "deploy" / "dev" / "sources" / "files" / "clinical",
    "dev-files-s3": ROOT / "deploy" / "dev" / "sources" / "s3" / "clinical-archive",
}
OPEN_QUERIES_SQL = (
    "SELECT count(*) FROM argos.connector_queries WHERE system_id = %s AND finished_at IS NULL"
)


@pytest.mark.parametrize("name", sorted(TREES))
def test_walks_and_samples_without_changing_the_tree(migrated_db: str, name: str) -> None:
    tree: Path = TREES[name]
    before = prepare.tree_manifest(tree)
    connector = open_source_connector(name, FilesConnector, migrated_db)
    try:
        scan = connector.execute(ProbeSpec("scan_schema", ""))
        assert scan.ok and scan.data["total"] == len(before)
        pdfs = connector.execute(ProbeSpec("count", "", params={"glob": "*.pdf"}))
        assert pdfs.ok and pdfs.data["count"] == sum(1 for p in before if p.endswith(".pdf"))
        # The whole tree: the first sorted entries of the local share are all admin, no DICOM.
        sample = connector.execute(ProbeSpec("sample", "", params={"k": len(before)}))
        assert sample.ok and "dicom" in {e["type"] for e in sample.data["entries"]}
        assert "SYN" not in repr(sample)
        acl = connector.execute(ProbeSpec("check_config", ""))
        assert acl.ok
    finally:
        connector.close()
    assert prepare.tree_manifest(tree) == before
    with psycopg.connect(migrated_db) as conn:
        open_rows = conn.execute(OPEN_QUERIES_SQL, (connector.system_id,)).fetchone()
    assert open_rows == (0,)
