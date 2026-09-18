"""ARG-063 · Merkle tree: exact vectors, inclusion and corruption always detected."""

import hashlib
import json
import random
from pathlib import Path
from typing import Any

import pytest

from argos_evidence.merkle import (
    MerkleTree,
    build_tree,
    failing_leaves,
    proof,
    verify_proof,
)

VECTORS = Path(__file__).parents[3] / "tests" / "vectors" / "merkle_v1.json"
SEED = 20260918
CORRUPTION_TRIALS = 2000


def _vectors() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(VECTORS.read_text(encoding="utf-8"))
    return data


def _hashes(count: int, salt: str = "") -> list[bytes]:
    return [hashlib.sha256(f"{salt}artifact-{i}".encode()).digest() for i in range(count)]


def _flip(value: bytes, rng: random.Random) -> bytes:
    position = rng.randrange(len(value))
    mask = rng.randrange(1, 256)
    return value[:position] + bytes([value[position] ^ mask]) + value[position + 1 :]


# --- exact vectors -----------------------------------------------------------


@pytest.mark.parametrize("case", _vectors()["trees"], ids=lambda c: f"{c['size']}-leaves")
def test_the_tree_matches_the_vectors(case: dict[str, Any]) -> None:
    leaves = [bytes.fromhex(h) for h in case["leaves"]]
    tree = build_tree(leaves)
    assert tree.size == case["size"]
    assert tree.root.hex() == case["root"]
    assert [[h.hex() for h in level] for level in tree.levels] == case["levels"]
    for index, expected in enumerate(case["proofs"]):
        path = proof(tree, index)
        assert [(side, sibling.hex()) for side, sibling in path] == [
            (step["side"], step["hash"]) for step in expected
        ]
        assert verify_proof(leaves[index], index, tree.size, path, tree.root)


def test_promotion_does_not_collide_where_duplication_would() -> None:
    case = _vectors()["duplication_counterexample"]
    root_a = build_tree([bytes.fromhex(h) for h in case["leaves_a"]]).root
    root_b = build_tree([bytes.fromhex(h) for h in case["leaves_b"]]).root
    assert root_a.hex() == case["root_a"]
    assert root_b.hex() == case["root_b"]
    assert root_a != root_b


# --- inclusion ---------------------------------------------------------------


@pytest.mark.parametrize("size", range(1, 65))
def test_every_leaf_proves_its_inclusion(size: int) -> None:
    leaves = _hashes(size)
    tree = build_tree(leaves)
    for index, leaf in enumerate(leaves):
        assert verify_proof(leaf, index, size, proof(tree, index), tree.root)


@pytest.mark.parametrize("size", range(2, 65))
def test_a_proof_does_not_verify_at_another_position(size: int) -> None:
    leaves = _hashes(size)
    tree = build_tree(leaves)
    for index, leaf in enumerate(leaves):
        path = proof(tree, index)
        for other in range(size):
            if other != index:
                assert not verify_proof(leaf, other, size, path, tree.root)


def test_a_proof_does_not_verify_against_another_tree_size() -> None:
    leaves = _hashes(5)
    tree = build_tree(leaves)
    path = proof(tree, 4)
    assert verify_proof(leaves[4], 4, 5, path, tree.root)
    assert not verify_proof(leaves[4], 4, 6, path, tree.root)


def test_out_of_range_positions_are_rejected() -> None:
    tree = build_tree(_hashes(3))
    with pytest.raises(IndexError):
        proof(tree, 3)
    assert not verify_proof(_hashes(3)[0], 3, 3, [], tree.root)
    assert not verify_proof(_hashes(3)[0], -1, 3, [], tree.root)


# --- one corrupted byte is always detected -----------------------------------


def test_one_corrupted_byte_is_always_detected_and_located() -> None:
    rng = random.Random(SEED)  # noqa: S311 - reproducible corruptions, not cryptography
    targets_hit = {"leaf": 0, "proof": 0, "root": 0}
    for _ in range(CORRUPTION_TRIALS):
        size = rng.randint(1, 64)
        leaves = _hashes(size, salt=str(rng.random()))
        tree = build_tree(leaves)
        index = rng.randrange(size)
        path = proof(tree, index)
        target = rng.choice(["leaf", "proof", "root"] if path else ["leaf", "root"])
        targets_hit[target] += 1

        if target == "leaf":
            corrupted = list(leaves)
            corrupted[index] = _flip(leaves[index], rng)
            assert not verify_proof(corrupted[index], index, size, path, tree.root)
            assert failing_leaves(corrupted, tree) == [index]
        elif target == "proof":
            step = rng.randrange(len(path))
            side, sibling = path[step]
            broken = [*path[:step], (side, _flip(sibling, rng)), *path[step + 1 :]]
            assert not verify_proof(leaves[index], index, size, broken, tree.root)
        else:
            assert not verify_proof(leaves[index], index, size, path, _flip(tree.root, rng))

    assert all(count > 0 for count in targets_hit.values())


def test_an_intact_campaign_has_no_failing_leaves() -> None:
    leaves = _hashes(17)
    assert failing_leaves(leaves, build_tree(leaves)) == []


def test_a_missing_or_extra_artifact_is_an_error_not_a_pass() -> None:
    leaves = _hashes(4)
    tree = build_tree(leaves)
    with pytest.raises(ValueError):
        failing_leaves(leaves[:3], tree)
    with pytest.raises(ValueError):
        failing_leaves([*leaves, leaves[0]], tree)


# --- invalid input -----------------------------------------------------------


def test_an_empty_tree_is_an_error_not_a_zero_root() -> None:
    with pytest.raises(ValueError):
        build_tree([])


def test_leaves_must_be_sha256_digests() -> None:
    with pytest.raises(ValueError):
        build_tree([b"short"])


def test_the_tree_is_immutable() -> None:
    tree = build_tree(_hashes(2))
    assert isinstance(tree, MerkleTree)
    with pytest.raises(AttributeError):
        tree.levels = ()  # type: ignore[misc]
