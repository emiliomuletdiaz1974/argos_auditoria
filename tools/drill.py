"""ARG-099 · the quarterly drill of the book of operation (F10-06).

    uv run python tools/drill.py --operator <name> [--seed N]

Draws two runbooks of docs/operacion/runbooks by lot and walks the operator through their five
sections, one at a time: symptom, diagnosis, action, verification and when to escalate. Each step
is confirmed with Enter, or answered "no" when it cannot be done as written. The drill is timed and
recorded in the journal as `ops.drill`: the runbooks, the seconds, the operator and whether every
step could be done. A step that could not be done is a correction of that runbook, not a failure of
the operator.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNBOOKS = REPO / "docs" / "operacion" / "runbooks"
SECTIONS = ("Síntoma", "Diagnóstico", "Acción", "Verificación", "Cuándo escalar")
DEV_ADMIN_DSN = "postgresql://argos@127.0.0.1:55432/argos"


@dataclass(frozen=True)
class Runbook:
    name: str
    title: str
    sections: dict[str, str]


@dataclass(frozen=True)
class Result:
    runbooks: list[str]
    seconds: float
    passed: bool
    failed_steps: list[str] = field(default_factory=list)


def runbooks(folder: Path = RUNBOOKS) -> list[Runbook]:
    found = []
    for path in sorted(folder.glob("RB-*.md")):
        text = path.read_text(encoding="utf-8").split("---\n", 2)[-1]
        title = next((line[2:] for line in text.splitlines() if line.startswith("# ")), path.stem)
        parts = re.split(r"^## ", text, flags=re.M)
        sections = {}
        for part in parts[1:]:
            heading, _, body = part.partition("\n")
            if heading.strip() in SECTIONS:
                sections[heading.strip()] = body.strip()
        found.append(Runbook(path.name, title, sections))
    return found


def draw(available: Sequence[Runbook], seed: int | None = None) -> list[Runbook]:
    """Two different runbooks by lot; with a seed, the same two every time."""
    chooser = random.Random(seed) if seed is not None else random.SystemRandom()  # noqa: S311
    return chooser.sample(list(available), 2)


def walk(
    chosen: Sequence[Runbook],
    ask: Callable[[str], str] = input,
    clock: Callable[[], float] = time.monotonic,
) -> Result:
    started = clock()
    failed: list[str] = []
    for runbook in chosen:
        for section in SECTIONS:
            text = runbook.sections.get(section, "(sin texto)")
            prompt = (
                f"\n[{runbook.name}] {section}\n{text}\n"
                "Hecho (Intro) o no se pudo hacer así ('no'): "
            )
            if ask(prompt).strip().lower() in {"no", "n"}:
                failed.append(f"{runbook.name}: {section}")
    return Result([r.name for r in chosen], clock() - started, not failed, failed)


def record(dsn: str, operator: str, result: Result) -> int:
    """The drill in the journal. Whole seconds: the canonical form of the journal has no floats."""
    from argos_common.journal_pg import PostgresJournal

    payload = {
        "runbooks": result.runbooks,
        "seconds": int(round(result.seconds)),
        "passed": result.passed,
        "failed_steps": result.failed_steps,
    }
    return PostgresJournal(dsn).append(f"user:{operator}", "ops.drill", payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--operator", required=True, help="who runs the drill")
    parser.add_argument("--seed", type=int, help="repeat a draw (for a second attempt)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    chosen = draw(runbooks(), args.seed)
    print("Simulacro: " + " y ".join(f"{r.name} ({r.title})" for r in chosen))
    result = walk(chosen)
    seq = record(os.environ.get("ARGOS_DRILL_DSN", DEV_ADMIN_DSN), args.operator, result)
    minutes = result.seconds / 60
    print(f"\n{minutes:.1f} minutos; asiento {seq} del diario (ops.drill).")
    for step in result.failed_steps:
        print(f"  - corregir el runbook: {step}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
