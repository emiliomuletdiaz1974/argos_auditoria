"""Compute the ARG-063 Merkle test vectors.

Written on purpose without importing the evidence package: the vectors must
exist before the tree implementation and must not share code with it.

    uv run python tools/merkle_vectors.py          # rewrite the vectors file
    uv run python tools/merkle_vectors.py --check  # exit 1 if it is stale
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

VECTORS = Path(__file__).parents[1] / "tests" / "vectors" / "merkle_v1.json"
VERSION = "ARGOS-MERKLE-v1"
LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"
SIZES = (1, 2, 3, 4, 5, 7)


def artifact_hash(index: int) -> bytes:
    """Stand-in for the SHA-256 of the artifact at ``index``."""
    return hashlib.sha256(f"artifact-{index}".encode("ascii")).digest()


def _leaf(artifact_sha256: bytes) -> bytes:
    return hashlib.sha256(LEAF_PREFIX + artifact_sha256).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


def levels_of(artifacts: list[bytes], duplicate_odd: bool = False) -> list[list[bytes]]:
    """All levels, leaves first. An odd last node is promoted unless ``duplicate_odd``."""
    levels = [[_leaf(a) for a in artifacts]]
    while len(levels[-1]) > 1:
        current = list(levels[-1])
        promoted = None
        if len(current) % 2 == 1:
            if duplicate_odd:
                current.append(current[-1])
            else:
                promoted = current.pop()
        parents = [_node(current[i], current[i + 1]) for i in range(0, len(current), 2)]
        if promoted is not None:
            parents.append(promoted)
        levels.append(parents)
    return levels


def proof_of(levels: list[list[bytes]], index: int) -> list[dict[str, str]]:
    """Siblings from the leaf up; a promoted node contributes no step."""
    steps = []
    position = index
    for level in levels[:-1]:
        if position % 2 == 1:
            steps.append({"side": "L", "hash": level[position - 1].hex()})
        elif position + 1 < len(level):
            steps.append({"side": "R", "hash": level[position + 1].hex()})
        position //= 2
    return steps


def _tree(size: int) -> dict[str, Any]:
    artifacts = [artifact_hash(i) for i in range(size)]
    levels = levels_of(artifacts)
    return {
        "size": size,
        "leaves": [a.hex() for a in artifacts],
        "levels": [[h.hex() for h in level] for level in levels],
        "root": levels[-1][0].hex(),
        "proofs": [proof_of(levels, i) for i in range(size)],
    }


def _duplication_counterexample() -> dict[str, Any]:
    leaves_a = [artifact_hash(i) for i in range(3)]
    leaves_b = [*leaves_a, leaves_a[-1]]
    return {
        "note": (
            "Duplicating the last node of an odd level would give these two different "
            "leaf lists the same root; promoting it keeps them apart."
        ),
        "leaves_a": [a.hex() for a in leaves_a],
        "leaves_b": [a.hex() for a in leaves_b],
        "root_a_if_duplicated": levels_of(leaves_a, duplicate_odd=True)[-1][0].hex(),
        "root_b_if_duplicated": levels_of(leaves_b, duplicate_odd=True)[-1][0].hex(),
        "root_a": levels_of(leaves_a)[-1][0].hex(),
        "root_b": levels_of(leaves_b)[-1][0].hex(),
    }


def build_vectors() -> dict[str, Any]:
    return {
        "version": VERSION,
        "hash": "sha256",
        "leaf_prefix": LEAF_PREFIX.hex(),
        "node_prefix": NODE_PREFIX.hex(),
        "leaf_input": "sha256(ascii('artifact-<index>'))",
        "trees": [_tree(size) for size in SIZES],
        "duplication_counterexample": _duplication_counterexample(),
    }


def render(vectors: dict[str, Any]) -> str:
    return json.dumps(vectors, indent=2, ensure_ascii=True) + "\n"


def main(argv: list[str]) -> int:
    text = render(build_vectors())
    if "--check" in argv:
        current = VECTORS.read_text(encoding="utf-8") if VECTORS.exists() else ""
        if current != text:
            print(f"{VECTORS} is stale; run tools/merkle_vectors.py")
            return 1
        print("merkle vectors up to date")
        return 0
    VECTORS.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {VECTORS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
