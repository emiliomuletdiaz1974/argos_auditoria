"""Phase 4 acceptance test (Plan Director §8.2 "Fase 04").

1. The v1 library (GDPR, EHDS and AI Act populations) passes the five editorial gates.
2. Its bundle is reproducible, signed with the content key in Vault, verified and loaded; a bundle
   whose content changed after signing is rejected before reaching the store.
3. Applicability of the loaded bundle on the demo snapshot equals the applicability ground truth
   on every campaign date.
4. A planted editorial error is rejected by its gate.
5. The SHACL, OPA and ODRL engines answer on the same snapshot.
"""

import os
import shutil
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import httpx
import psycopg
import pytest
from fixtures.applicability_ground_truth import ExpectedRequirement, load_applicability_truth
from fixtures.demo_review import apply_demo_review
from integration.conftest import ADMIN_DSN, MIGRATIONS_DIR
from integration.inventory_helpers import probe_runner, scan_and_ingest
from psycopg import sql

from argos_common.migrations import apply_migrations
from argos_common.release import VaultTransitSigner
from argos_inventory.ai_discovery.detect import discover_ai
from argos_inventory.classify.deterministic import classify_new_columns
from argos_inventory.graph.model import system_key
from argos_inventory.graph.store import GraphStore
from argos_ontology.bundle import BundleRejectedError, build_bundle, load_bundle, sign_bundle
from argos_ontology.editorial.compiler import compile_file
from argos_ontology.gates import GateResult, run_gates
from argos_ontology.odrl import parse_policy, to_challenges
from argos_ontology.opa import evaluate
from argos_ontology.resolver import StoreSelectorResolver, resolve
from argos_ontology.shacl import run_shapes
from argos_ontology.store import OntologyStore
from argos_ontology.vocabulary import LIBRARY_DIR, NORMS

pytestmark = pytest.mark.integration

VAULT = os.environ.get("ARGOS_TEST_VAULT", "http://127.0.0.1:8200")
VAULT_TOKEN = os.environ.get("ARGOS_TEST_VAULT_TOKEN", "root")
CONTENT_KEY = os.environ.get("ARGOS_TEST_CONTENT_KEY", "argos-content")
OPA = os.environ.get("ARGOS_TEST_OPA", "http://127.0.0.1:8181")
OPA_TOKEN = os.environ.get("ARGOS_TEST_OPA_TOKEN", "dev-only-opa-host")
VERSION = "1.0.0"
IN_FORCE = date(2024, 8, 1)
TRUTH = load_applicability_truth()
NODE_NAMES = (
    "MATCH (s:System) WITH s MATCH (n) WHERE coalesce(n.system_id, n.id) = s.id "
    "RETURN n.key, s.name, coalesce(n.qualified_name, n.name)"
)


def _failing(results: list[GateResult]) -> dict[str, tuple[str, ...]]:
    return {r.name: tuple(r.errors) for r in results if not r.ok}


@pytest.fixture
def phase4_db() -> Iterator[str]:
    name = f"argos_phase4_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        dsn = f"{ADMIN_DSN.rsplit('/', 1)[0]}/{name}"
        apply_migrations(dsn, MIGRATIONS_DIR)
        yield dsn
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
            conn.execute(drop.format(sql.Identifier(name)))


def test_the_v1_library_passes_the_five_gates() -> None:
    assert _failing(run_gates(LIBRARY_DIR)) == {}


def test_a_planted_editorial_error_is_rejected_by_its_gate(tmp_path: Path) -> None:
    library = tmp_path / "library"
    shutil.copytree(LIBRARY_DIR, library)
    template = library / "ontology" / "editorial" / "OBL-RGPD-99-1.yaml"
    template.write_text(
        'id: OBL-RGPD-99-1\nnorma: RGPD\narticulo: "99"\ntitulo: Artículo inexistente\n'
        "vigente_desde: 2018-05-25\nseveridad: low\naplica_a: [AC-stored-health-data]\n"
        "verificado_por: [sec-encryption-at-rest]\n",
        encoding="utf-8",
    )
    generated = library / "ontology" / "norms" / "generated" / "OBL-RGPD-99-1.ttl"
    generated.write_bytes(compile_file(template))
    failing = _failing(run_gates(library))
    assert "traceability" in failing
    assert any("RGPD-99" in error for error in failing["traceability"])


def test_signed_bundle_applicability_and_engines_on_the_demo_snapshot(
    phase4_db: str, tmp_path: Path
) -> None:
    # 2. Reproducible bundle, signed in Vault, verified and loaded; tampering is rejected.
    bundle, manifest = build_bundle(LIBRARY_DIR, VERSION, IN_FORCE)
    assert build_bundle(LIBRARY_DIR, VERSION, IN_FORCE)[0] == bundle
    signer = VaultTransitSigner(VAULT, VAULT_TOKEN, key=CONTENT_KEY)
    signature, public_key = sign_bundle(manifest, signer), signer.public_key()
    altered_library = tmp_path / "library"
    shutil.copytree(LIBRARY_DIR, altered_library)
    catalog = altered_library / "challenges" / "catalog.yaml"
    catalog.write_text(catalog.read_text(encoding="utf-8") + "# altered\n", encoding="utf-8")
    altered, _ = build_bundle(altered_library, VERSION, IN_FORCE)
    with pytest.raises(BundleRejectedError):
        load_bundle(phase4_db, altered, signature, public_key)
    with psycopg.connect(phase4_db) as conn:
        assert conn.execute("SELECT count(*) FROM argos.ontology_bundles").fetchone() == (0,)
    record = load_bundle(phase4_db, bundle, signature, public_key)
    assert (record.version, record.in_force_from) == (VERSION, IN_FORCE)

    # 3. Applicability on the demo snapshot equals the ground truth on every date.
    store = GraphStore(phase4_db)
    system_ids = {}
    for name in TRUTH.systems:
        system_ids[name] = scan_and_ingest(phase4_db, name)
        classify_new_columns(store, probe_runner(phase4_db), system_ids[name])
    discover_ai(store)
    apply_demo_review(store, phase4_db, system_ids)
    names = {
        str(row["key"]): f"{row['system']} {row['name']}"
        for row in store.query(NODE_NAMES, columns=("key", "system", "name"))
    }
    ontology = OntologyStore(phase4_db, VERSION)
    for at in sorted(TRUTH.dates):
        run = resolve(phase4_db, ontology, StoreSelectorResolver(store), {}, at=at)
        found = {
            ExpectedRequirement(
                row["obligation"].removeprefix(str(NORMS)),
                row["asset_class"].removeprefix(str(NORMS)),
                row["challenge_id"],
                frozenset(names[key] for key in row["node_keys"]),
            )
            for row in run.plan
        }
        assert run.skipped == [], at
        assert (at, sorted(found ^ TRUTH.expected_plan(at))) == (at, [])

    # 5a. SHACL: both systems hold health data and none is in the record of processing, and the
    # confirmed AI system declares neither technical documentation nor human oversight (F05-18).
    findings = {(f.node, f.shape, f.severity) for f in run_shapes(store)}
    expected = {
        (system_key(system_id), "HealthDataSystemShape", "violation")
        for system_id in system_ids.values()
    }
    ai_shapes = {"AISystemDocumentationShape", "AIHumanOversightShape"}
    assert {entry for entry in findings if entry[1] not in ai_shapes} == expected
    assert {shape for _, shape, _ in findings if shape in ai_shapes} == ai_shapes

    # 5b. OPA: the retention rule answers with the synthetic client schedule.
    httpx.get(f"{OPA}/health", timeout=5.0).raise_for_status()
    verdict = evaluate(
        "argos.retention",
        {
            "category": "special_category.health",
            "treatment": "HIS-episodes",
            "max_age_days": 100,
            "out_of_term": 0,
            "documented_exceptions": 0,
        },
        OPA,
        token=OPA_TOKEN,
    )
    assert verdict == {
        "compliant": True,
        "applied_term_days": 5475,
        "out_of_term": 0,
        "rule": "argos.retention",
    }

    # 5c. ODRL: a data space policy becomes challenges plus an honest unverifiable finding.
    policy = parse_policy(
        {
            "uid": "urn:dataspace:policy:demo",
            "target": "urn:dataspace:asset:demo-cohort",
            "permission": [
                {
                    "action": "use",
                    "constraint": [
                        {"leftOperand": "purpose", "operator": "eq", "rightOperand": "research"}
                    ],
                }
            ],
            "obligation": [{"action": "compensate"}],
        }
    )
    assert [c["template"] for c in to_challenges(policy)] == [
        "ds-usage-purpose",
        "ds-unverifiable",
    ]
