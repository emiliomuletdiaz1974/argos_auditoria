"""Merkle tree of a campaign's evidence (ARG-063).

Leaves and inner nodes are hashed with different domain prefixes (0x00 and
0x01), and an odd node at the end of a level is promoted unchanged instead of
duplicated: duplicating it would give two different leaf lists the same root.

This file depends only on the standard library. It is shipped next to the
campaign record so anyone can check an artifact without ARGOS:

    python merkle.py <artifact file> <proof.json>

where proof.json is {"index": int, "size": int, "path": [["L"|"R", hex], ...],
"root": hex}. Exit code 0 means the artifact belongs to the tree with that root.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"
DIGEST_SIZE = 32

Step = tuple[str, bytes]


def _leaf(artifact_sha256: bytes) -> bytes:
    return hashlib.sha256(LEAF_PREFIX + artifact_sha256).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


@dataclass(frozen=True)
class MerkleTree:
    """Every level of the tree, leaf nodes first and the root last."""

    levels: tuple[tuple[bytes, ...], ...]

    @property
    def root(self) -> bytes:
        return self.levels[-1][0]

    @property
    def size(self) -> int:
        return len(self.levels[0])


def build_tree(artifact_hashes: list[bytes]) -> MerkleTree:
    """Build the tree over the SHA-256 digests of the artifacts, in the given order."""
    if not artifact_hashes:
        raise ValueError("a campaign without artifacts has no Merkle root")
    if any(len(h) != DIGEST_SIZE for h in artifact_hashes):
        raise ValueError("every leaf must be a SHA-256 digest of 32 bytes")
    level = tuple(_leaf(h) for h in artifact_hashes)
    levels = [level]
    while len(level) > 1:
        parents = [_node(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2 == 1:
            parents.append(level[-1])
        level = tuple(parents)
        levels.append(level)
    return MerkleTree(tuple(levels))


def _expected_sides(index: int, size: int) -> list[str]:
    """Side of each sibling on the way up; promoted levels contribute no step."""
    sides = []
    while size > 1:
        if index % 2 == 1:
            sides.append("L")
        elif index + 1 < size:
            sides.append("R")
        index //= 2
        size = (size + 1) // 2
    return sides


def proof(tree: MerkleTree, index: int) -> list[Step]:
    """Inclusion proof of the leaf at ``index``: its siblings from the bottom up."""
    if not 0 <= index < tree.size:
        raise IndexError(f"leaf {index} is outside a tree of {tree.size}")
    steps: list[Step] = []
    position = index
    for level in tree.levels[:-1]:
        if position % 2 == 1:
            steps.append(("L", level[position - 1]))
        elif position + 1 < len(level):
            steps.append(("R", level[position + 1]))
        position //= 2
    return steps


def verify_proof(
    artifact_sha256: bytes, index: int, size: int, path: list[Step], root: bytes
) -> bool:
    """True when the artifact sits at ``index`` of a tree of ``size`` leaves with ``root``.

    The shape of the path is derived from index and size, so a proof presented
    for another position or another tree size does not verify.
    """
    if not 0 <= index < size or len(artifact_sha256) != DIGEST_SIZE:
        return False
    if [side for side, _ in path] != _expected_sides(index, size):
        return False
    current = _leaf(artifact_sha256)
    for side, sibling in path:
        if len(sibling) != DIGEST_SIZE:
            return False
        current = _node(sibling, current) if side == "L" else _node(current, sibling)
    return current == root


def failing_leaves(artifact_hashes: list[bytes], tree: MerkleTree) -> list[int]:
    """Positions whose artifact no longer matches the tree, in order."""
    if len(artifact_hashes) != tree.size:
        raise ValueError(
            f"the tree has {tree.size} leaves but {len(artifact_hashes)} artifacts were given"
        )
    return [
        index
        for index, digest in enumerate(artifact_hashes)
        if not verify_proof(digest, index, tree.size, proof(tree, index), tree.root)
    ]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python merkle.py <artifact file> <proof.json>")
        return 2
    with open(argv[0], "rb") as artifact_file:
        digest = hashlib.sha256(artifact_file.read()).digest()
    with open(argv[1], encoding="utf-8") as proof_file:
        document = json.load(proof_file)
    path = [(str(side), bytes.fromhex(sibling)) for side, sibling in document["path"]]
    ok = verify_proof(
        digest, int(document["index"]), int(document["size"]), path, bytes.fromhex(document["root"])
    )
    print("OK: the artifact belongs to the tree" if ok else "FAIL: the artifact does not match")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
