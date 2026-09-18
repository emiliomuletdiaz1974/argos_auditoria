"""ARG-063 · Merkle vectors exist before the tree and come from an independent script."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).parents[2]
TOOL = ROOT / "tools" / "merkle_vectors.py"
VECTORS = ROOT / "tests" / "vectors" / "merkle_v1.json"
SIZES = [1, 2, 3, 4, 5, 7]


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("merkle_vectors", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _vectors() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(VECTORS.read_text(encoding="utf-8"))
    return data


def _sha(*parts: bytes) -> bytes:
    return hashlib.sha256(b"".join(parts)).digest()


def _fold(leaf_hex: str, proof: list[dict[str, str]]) -> str:
    current = _sha(b"\x00", bytes.fromhex(leaf_hex))
    for step in proof:
        sibling = bytes.fromhex(step["hash"])
        if step["side"] == "L":
            current = _sha(b"\x01", sibling, current)
        else:
            current = _sha(b"\x01", current, sibling)
    return current.hex()


def test_the_file_declares_its_version_and_domain_prefixes() -> None:
    data = _vectors()
    assert data["version"] == "ARGOS-MERKLE-v1"
    assert data["leaf_prefix"] == "00"
    assert data["node_prefix"] == "01"


def test_the_file_covers_the_required_tree_sizes() -> None:
    assert [tree["size"] for tree in _vectors()["trees"]] == SIZES
    for tree in _vectors()["trees"]:
        assert len(tree["leaves"]) == tree["size"]
        assert len(tree["proofs"]) == tree["size"]
        assert tree["levels"][-1] == [tree["root"]]


def test_small_roots_match_a_hand_computation() -> None:
    one, two = _vectors()["trees"][:2]
    assert one["root"] == _sha(b"\x00", bytes.fromhex(one["leaves"][0])).hex()
    left = _sha(b"\x00", bytes.fromhex(two["leaves"][0]))
    right = _sha(b"\x00", bytes.fromhex(two["leaves"][1]))
    assert two["root"] == _sha(b"\x01", left, right).hex()


def test_every_proof_leads_to_its_root() -> None:
    for tree in _vectors()["trees"]:
        for leaf, proof in zip(tree["leaves"], tree["proofs"], strict=True):
            assert _fold(leaf, proof) == tree["root"]


def test_odd_levels_promote_the_last_node_unchanged() -> None:
    three = _vectors()["trees"][2]
    assert three["levels"][1][1] == three["levels"][0][2]


def test_the_duplication_case_shows_the_collision_it_avoids() -> None:
    case = _vectors()["duplication_counterexample"]
    assert case["leaves_b"] == [*case["leaves_a"], case["leaves_a"][-1]]
    assert case["root_a_if_duplicated"] == case["root_b_if_duplicated"]
    assert case["root_a"] != case["root_b"]


def test_the_script_regenerates_the_stored_file_byte_for_byte() -> None:
    tool = _tool()
    assert tool.render(tool.build_vectors()) == VECTORS.read_text(encoding="utf-8")


def test_the_script_is_independent_of_the_evidence_package() -> None:
    source = TOOL.read_text(encoding="utf-8")
    assert "argos_evidence" not in source
    assert "argos_" not in source
