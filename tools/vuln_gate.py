"""ARG-087 · the vulnerability gate over the grype report of each SBOM (F09-09, ADR-0014 point 6).

uv run python tools/vuln_gate.py [--sbom dist/sbom] [--vex platform/security/vex.yaml]

A finding blocks the release when it is:
  * a critical with a fix published;
  * a high whose fix was first seen more than 30 days ago, or with no date (then nobody can say
    it is recent).
Everything else of high or critical severity is a warning; below that it is not reported.

An exception in `vex.yaml` (vulnerability, package, justification, author and expiry) lets a
finding through while it is in force. An expired exception breaks the gate by itself: whoever
granted it has to look again. An exception without justification, author or expiry does not load.
"""

import argparse
import datetime as dt
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
HIGH_FIX_GRACE = dt.timedelta(days=30)
REPORTED = {"Critical", "High"}


@dataclass(frozen=True, slots=True)
class Exception_:  # noqa: N801 - "Exception" is taken by Python
    id: str
    package: str
    justification: str
    author: str
    expires: dt.date
    component: str | None = None


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    severity: str
    package: str
    version: str
    component: str
    fix: str
    reason: str = ""


@dataclass
class Result:
    blocking: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    excepted: list[Finding] = field(default_factory=list)
    expired: list[Exception_] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.blocking and not self.expired


def load_exceptions(path: Path) -> list[Exception_]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    loaded = []
    for number, entry in enumerate(raw.get("exceptions") or [], start=1):
        for key in ("id", "package", "justification", "author", "expires"):
            if not str(entry.get(key) or "").strip():
                raise ValueError(f"{path.name}: exception {number} has no {key}")
        expires = entry["expires"]
        loaded.append(
            Exception_(
                id=str(entry["id"]),
                package=str(entry["package"]),
                justification=str(entry["justification"]),
                author=str(entry["author"]),
                expires=expires if isinstance(expires, dt.date) else dt.date.fromisoformat(expires),
                component=entry.get("component"),
            )
        )
    return loaded


def _first_fix(fix: dict[str, Any]) -> dt.date | None:
    dates = [dt.date.fromisoformat(a["date"]) for a in fix.get("available") or [] if a.get("date")]
    return min(dates) if dates else None


def _findings(folder: Path, today: dt.date) -> Iterator[tuple[Finding, bool]]:
    """Each high or critical finding and whether it blocks by the rule."""
    for report in sorted(folder.glob("*.vulns.json")):
        component = report.name.removesuffix(".vulns.json")
        for match in json.loads(report.read_text(encoding="utf-8")).get("matches", []):
            vulnerability, artifact = match["vulnerability"], match["artifact"]
            severity = str(vulnerability.get("severity"))
            if severity not in REPORTED:
                continue
            fix = vulnerability.get("fix") or {}
            fixed = fix.get("state") == "fixed"
            first = _first_fix(fix)
            if severity == "Critical":
                blocks, reason = fixed, "critical with a fix published"
            else:
                old = first is None or today - first > HIGH_FIX_GRACE
                blocks = fixed and old
                reason = (
                    f"high with a fix first seen on {first}"
                    if first
                    else "high with a fix of unknown date"
                )
            yield (
                Finding(
                    id=str(vulnerability["id"]),
                    severity=severity,
                    package=str(artifact["name"]),
                    version=str(artifact.get("version", "")),
                    component=component,
                    fix=", ".join(fix.get("versions") or []) or str(fix.get("state") or "none"),
                    reason=reason if blocks else "",
                ),
                blocks,
            )


def evaluate(folder: Path, exceptions: list[Exception_], today: dt.date) -> Result:
    result = Result(expired=[e for e in exceptions if e.expires < today])
    in_force = [e for e in exceptions if e.expires >= today]
    for finding, blocks in _findings(folder, today):
        covered = any(
            e.id == finding.id
            and e.package == finding.package
            and (e.component is None or e.component == finding.component)
            for e in in_force
        )
        if covered:
            result.excepted.append(finding)
        elif blocks:
            result.blocking.append(finding)
        else:
            result.warnings.append(finding)
    return result


def _line(finding: Finding) -> str:
    return (
        f"  {finding.severity:8} {finding.id:20} {finding.component}: "
        f"{finding.package} {finding.version} (fix: {finding.fix})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sbom", type=Path, default=ROOT / "dist" / "sbom")
    parser.add_argument("--vex", type=Path, default=ROOT / "platform" / "security" / "vex.yaml")
    args = parser.parse_args(argv)
    if not list(args.sbom.glob("*.vulns.json")):
        print(f"no grype report in {args.sbom}: run tools/sbom.py first", file=sys.stderr)
        return 2
    result = evaluate(args.sbom, load_exceptions(args.vex), dt.date.today())
    for title, found in (("blocking", result.blocking), ("warnings", result.warnings)):
        print(f"{title}: {len(found)}")
        for finding in sorted(found, key=lambda f: (f.component, f.severity, f.id)):
            print(_line(finding) + (f" — {finding.reason}" if finding.reason else ""))
    print(f"excepted in vex.yaml: {len(result.excepted)}")
    for expired in result.expired:
        print(f"  EXPIRED exception {expired.id} ({expired.package}) on {expired.expires}")
    print("vulnerability gate: " + ("passed" if result.passed else "FAILED"))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
