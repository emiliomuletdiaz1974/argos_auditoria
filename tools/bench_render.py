"""K-02 · the bench is deployed only from a tag `banco-vX.Y.Z`, with each image pinned by digest.

The workflow `.github/workflows/bench.yml` calls this twice:

  uv run python tools/bench_render.py version banco-v0.1.0     -> 0.1.0 (anything else stops it)
  uv run python tools/bench_render.py render --digests <dir> --owner <github owner> --out <dir>

`render` writes a kustomization over the `bench-gcp` overlay that replaces every image of ARGOS by
the one the workflow just built, signed and pushed to GHCR, by its digest: what Flux applies on
the VM is exactly what was signed, never a tag that could move.
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "platform" / "k8s" / "overlays" / "bench-gcp"
TAG = re.compile(r"^banco-v(\d+\.\d+\.\d+)$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class Image:
    dockerfile: str
    component: str
    context: str = "."


# The images `make build` builds, by the name the manifests use for them.
IMAGES = {
    "argos-example": Image("services/example/Dockerfile", "ARG-001"),
    "argos-challenge-engine": Image("services/challenge-engine/Dockerfile", "ARG-043"),
    "argos-ai-gateway": Image("services/ai-gateway/Dockerfile", "ARG-052"),
    "argos-api": Image("services/api/Dockerfile", "ARG-071"),
    "argos-evidence": Image("services/evidence/Dockerfile", "ARG-061"),
    "argos-verifier": Image("services/verifier/Dockerfile", "ARG-069"),
    "argos-health": Image("services/health/Dockerfile", "ARG-094"),
}
# Images the bench builds that are not services of ARGOS: they come from the development
# environment, each from its own folder (K-03).
BENCH_IMAGES = {
    "argos-postgres": Image("deploy/dev/postgres/Dockerfile", "ARG-004", "deploy/dev/postgres"),
    "argos-opa": Image("platform/k8s/images/opa/Dockerfile", "ARG-036"),
    "argos-tsa": Image("deploy/dev/tsa/Dockerfile", "ARG-065", "deploy/dev/tsa"),
    "argos-keycloak": Image("platform/k8s/images/keycloak/Dockerfile", "ARG-008"),
    "argos-bench-seed": Image("platform/k8s/images/bench-seed/Dockerfile", "ARG-014"),
}
ALL_IMAGES = IMAGES | BENCH_IMAGES
# K-99: what the bench does not deploy, and why; the workflow neither builds nor pins it.
NOT_IN_THE_BENCH = {
    "argos-example": "the example service of F1-06, a template, not part of the product",
    "argos-ai-gateway": "the AI layer waits for a GPU (F06-05); the API answers 503 meanwhile",
}
BUILT = {name: image for name, image in ALL_IMAGES.items() if name not in NOT_IN_THE_BENCH}


def version_of(tag: str) -> str:
    """The semantic version of a bench tag; any other tag is refused."""
    match = TAG.fullmatch(tag)
    if match is None:
        raise ValueError("the bench is deployed only from a tag banco-vX.Y.Z")
    return match.group(1)


def render(digests: dict[str, str], owner: str, out: Path) -> dict[str, Any]:
    """Write `out/kustomization.yaml`: the bench overlay with every image pinned by digest."""
    registry = f"ghcr.io/{owner.lower()}"
    images = []
    for name in BUILT:
        digest = digests.get(name, "")
        if not DIGEST.fullmatch(digest):
            raise ValueError(f"{name}: no sha256 digest from the build")
        images.append({"name": name, "newName": f"{registry}/{name}", "digest": digest})
    kustomization: dict[str, Any] = {
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": [Path(os.path.relpath(OVERLAY, out.resolve())).as_posix()],
        "images": images,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "kustomization.yaml").write_text(yaml.safe_dump(kustomization, sort_keys=False), "utf-8")
    return kustomization


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    version = commands.add_parser("version")
    version.add_argument("tag")
    rendering = commands.add_parser("render")
    rendering.add_argument("--digests", type=Path, required=True)
    rendering.add_argument("--owner", required=True)
    rendering.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "version":
            print(version_of(args.tag))
            return 0
        digests = {
            name: (args.digests / name).read_text(encoding="utf-8").strip()
            for name in BUILT
            if (args.digests / name).is_file()
        }
        render(digests, args.owner, args.out)
    except ValueError as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
