"""ARG-099 · the quarterly drill: two runbooks drawn, timed and left in the journal (F10-06).

`tools/drill.py` draws two runbooks, walks the operator through their sections one by one, times
the drill and records it in the journal as `ops.drill`: which runbooks, how long, who and whether
it went well. The draw and the walk are pure; the record is tried on a disposable database.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]


def _drill() -> ModuleType:
    spec = importlib.util.spec_from_file_location("drill", REPO / "tools" / "drill.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["drill"] = module  # its dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


drill = _drill()


def test_two_different_runbooks_are_drawn_and_the_draw_repeats_with_its_seed() -> None:
    runbooks = drill.runbooks(REPO / "docs" / "operacion" / "runbooks")
    assert len(runbooks) == 12
    first = drill.draw(runbooks, seed=7)
    assert len(first) == 2 and first[0] != first[1]
    assert drill.draw(runbooks, seed=7) == first


def test_the_drill_walks_every_section_and_times_it() -> None:
    runbooks = drill.runbooks(REPO / "docs" / "operacion" / "runbooks")
    chosen = drill.draw(runbooks, seed=1)
    clock = iter([100.0, 460.0])
    seen: list[str] = []
    result = drill.walk(chosen, ask=lambda text: seen.append(text) or "", clock=lambda: next(clock))
    assert result.seconds == 360.0
    assert result.runbooks == [r.name for r in chosen]
    # Five sections of each runbook, and the operator confirms each one.
    assert len(seen) == 10
    assert all(any(s in text for s in ("Síntoma", "Diagnóstico", "Acción", "Verificación",
                                      "Cuándo escalar")) for text in seen)  # fmt: skip


def test_an_operator_who_answers_no_marks_the_drill_as_failed() -> None:
    runbooks = drill.runbooks(REPO / "docs" / "operacion" / "runbooks")
    chosen = drill.draw(runbooks, seed=2)
    answers = iter(["", "", "no", "", "", "", "", "", "", ""])
    result = drill.walk(chosen, ask=lambda _: next(answers), clock=lambda: 0.0)
    assert result.passed is False
    assert result.failed_steps


@pytest.mark.integration
def test_the_drill_is_recorded_in_the_journal(migrated_db: str) -> None:
    from argos_common.journal_pg import PostgresJournal

    seq = drill.record(
        migrated_db,
        "operador.prueba",
        drill.Result(["RB-01-diario.md", "RB-06-plataforma.md"], 360.0, True, []),
    )
    [entry] = list(PostgresJournal(migrated_db).read(seq, seq))
    assert entry.action == "ops.drill"
    assert entry.actor == "user:operador.prueba"
    assert '"seconds":360' in entry.payload_canon.replace(" ", "")
