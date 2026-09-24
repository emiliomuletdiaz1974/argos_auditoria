"""ARG-087 · the SBOM of every ARGOS image and of the console, and grype over each one (F09-09).

uv run python tools/sbom.py [--tag 0.1.0] [--out dist/sbom]

syft and grype run as images pinned by digest, never `latest`. Each image gets
`<name>.cdx.json` (CycloneDX) and `<name>.vulns.json` (the grype report); the console gets the
same from its `package-lock.json`. `tools/vuln_gate.py` then decides, and `tools/release.py build`
puts the hashes of both files in the signed manifest.

The grype database is downloaded once and kept (a docker volume, or ARGOS_GRYPE_CACHE in CI); grype
refuses a database older than five days. No SBOM may name a path of the machine that made it.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYFT = (
    "anchore/syft:v1.52.0@sha256:500e2d872ac019436926e8322b4fc1f39441d94d21f6f4046c6ff29b30e8cb02"
)
GRYPE = (
    "anchore/grype:v0.119.0@sha256:8c2c9234a345577a6d321a4753aa3ee1276d8975c8452d2344a56b57733ecad3"
)
IMAGES = (
    "argos-api",
    "argos-ai-gateway",
    "argos-challenge-engine",
    "argos-evidence",
    "argos-example",
    "argos-verifier",
)
CONSOLE = "console"


def _run(args: list[str]) -> bytes:
    done = subprocess.run(args, check=True, capture_output=True)  # noqa: S603 - fixed tools
    return done.stdout


def _no_local_paths(name: str, data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    for marker in {str(ROOT), ROOT.as_posix(), str(Path.home()), Path.home().as_posix()}:
        if marker and marker in text:
            raise SystemExit(f"the SBOM of {name} names a local path ({marker}): not published")


def sbom_of_image(image: str) -> bytes:
    return _run(
        [
            "docker", "run", "--rm",
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            SYFT, f"docker:{image}", "-o", "cyclonedx-json", "-q",
        ]
    )  # fmt: skip


def sbom_of_console() -> bytes:
    """From the lock file alone: what `npm ci` installs, development tools included."""
    lock, package = ROOT / "console" / "package-lock.json", ROOT / "console" / "package.json"
    return _run(
        [
            "docker", "run", "--rm",
            "-v", f"{lock}:/src/package-lock.json:ro",
            "-v", f"{package}:/src/package.json:ro",
            SYFT, "dir:/src", "-o", "cyclonedx-json", "-q",
        ]
    )  # fmt: skip


def vulnerabilities_of(out: Path, sbom_file: str) -> bytes:
    cache = os.environ.get("ARGOS_GRYPE_CACHE") or "argos-grype-db"
    return _run(
        [
            "docker", "run", "--rm",
            "-v", f"{cache}:/.cache/grype",
            "-v", f"{out.resolve()}:/sbom:ro",
            GRYPE, f"sbom:/sbom/{sbom_file}", "-o", "json", "-q",
        ]
    )  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", default=(ROOT / "VERSION").read_text(encoding="utf-8").strip())
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "sbom")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for stale in args.out.glob("*.json"):
        stale.unlink()
    targets = {name: lambda n=name: sbom_of_image(f"{n}:{args.tag}") for name in IMAGES}
    targets[CONSOLE] = sbom_of_console
    for name, make in targets.items():
        data = make()
        _no_local_paths(name, data)
        (args.out / f"{name}.cdx.json").write_bytes(data)
        report = vulnerabilities_of(args.out, f"{name}.cdx.json")
        (args.out / f"{name}.vulns.json").write_bytes(report)
        print(f"{name}: SBOM and vulnerability report in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
