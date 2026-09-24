"""F09-16 · the security dossier (ENS medium category and ISO/IEC 27001:2022), checked every run.

What an auditor reads has to hold: every measure and control is there, each with one of four
states; what is marked implemented links to evidence that exists in the repository; what only runs
in the development compose is not presented as implemented on the appliance; and what waits for
the hardware names the manual task that will do it.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOSSIER = REPO / "docs" / "seguridad" / "dossier"
STATES = {
    "implementada",
    "implementada en desarrollo",
    "pendiente de hardware",
    "responsabilidad del organismo",
}
# The manual tasks of the plan that wait for the appliance, a contract or an access.
MANUAL_TASKS = {"F1-11a", "F1-11b", "F02-98", "F06-98", "F07-14", "F07-15", "F07-16",
                "F09-90", "F09-91", "F09-92"}  # fmt: skip
ENS = {
    "org": [f"org.{n}" for n in range(1, 5)],
    "op.pl": [f"op.pl.{n}" for n in range(1, 6)],
    "op.acc": [f"op.acc.{n}" for n in range(1, 7)],
    "op.exp": [f"op.exp.{n}" for n in range(1, 11)],
    "op.ext": [f"op.ext.{n}" for n in range(1, 5)],
    "op.nub": ["op.nub.1"],
    "op.cont": [f"op.cont.{n}" for n in range(1, 5)],
    "op.mon": [f"op.mon.{n}" for n in range(1, 4)],
    "mp.if": [f"mp.if.{n}" for n in range(1, 8)],
    "mp.per": [f"mp.per.{n}" for n in range(1, 5)],
    "mp.eq": [f"mp.eq.{n}" for n in range(1, 5)],
    "mp.com": [f"mp.com.{n}" for n in range(1, 5)],
    "mp.si": [f"mp.si.{n}" for n in range(1, 6)],
    "mp.sw": ["mp.sw.1", "mp.sw.2"],
    "mp.info": [f"mp.info.{n}" for n in range(1, 7)],
    "mp.s": [f"mp.s.{n}" for n in range(1, 5)],
}
ISO = [f"5.{n}" for n in range(1, 38)] + [f"6.{n}" for n in range(1, 9)]
ISO += [f"7.{n}" for n in range(1, 15)] + [f"8.{n}" for n in range(1, 35)]
PATH = re.compile(r"`([^`]+)`")
TASK = re.compile(r"\bF(?:\d{2}|1)-\d{2}[ab]?\b")


def _rows(name: str) -> list[list[str]]:
    """The cells of every table row whose first cell is an identifier."""
    rows = []
    for line in (DOSSIER / name).read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if re.fullmatch(r"(org|op|mp)\.[a-z.]*\d+|\d\.\d+", cells[0]):
            rows.append(cells)
    return rows


def _check(rows: list[list[str]], state_col: int, evidence_col: int, task_col: int) -> list[str]:
    problems = []
    for cells in rows:
        ident, state = cells[0], cells[state_col]
        evidence = PATH.findall(cells[evidence_col])
        if state not in STATES:
            problems.append(f"{ident}: unknown state {state!r}")
            continue
        if state.startswith("implementada"):
            if not evidence:
                problems.append(f"{ident}: {state} without evidence")
            for path in evidence:
                if not (REPO / path.split("#")[0]).exists():
                    problems.append(f"{ident}: evidence {path} does not exist")
        if state == "implementada" and any(p.startswith("deploy/dev/") for p in evidence):
            problems.append(f"{ident}: evidence of the development compose is not the appliance")
        if state == "pendiente de hardware":
            cited = set(TASK.findall(cells[task_col]))
            if not cited & MANUAL_TASKS:
                problems.append(f"{ident}: pending hardware without its manual task")
    return problems


def test_every_measure_of_the_ens_is_there_once() -> None:
    listed = [cells[0] for cells in _rows("ens-medidas.md")]
    expected = [ident for family in ENS.values() for ident in family]
    assert sorted(listed) == sorted(expected)
    assert len(listed) == len(set(listed)) == 73


def test_every_control_of_annex_a_is_there_once() -> None:
    listed = [cells[0] for cells in _rows("iso27001-anexo-a.md")]
    assert sorted(listed, key=lambda c: tuple(map(int, c.split(".")))) == ISO
    assert len(ISO) == 93


@pytest.mark.parametrize("name", ["ens-medidas.md", "iso27001-anexo-a.md"])
def test_states_evidence_and_manual_tasks_hold(name: str) -> None:
    # Columns: | id | name | state | evidence | task |  (ISO adds the ENS measure after the name)
    shift = 1 if name.startswith("iso") else 0
    problems = _check(_rows(name), 2 + shift, 3 + shift, 4 + shift)
    assert problems == []


def test_the_ens_measures_quoted_by_iso_exist() -> None:
    known = {cells[0] for cells in _rows("ens-medidas.md")}
    for cells in _rows("iso27001-anexo-a.md"):
        for measure in re.findall(r"(?:org|op|mp)\.[a-z]+(?:\.\d+)?|org\.\d+", cells[2]):
            assert measure in known or any(k.startswith(measure + ".") for k in known), (
                cells[0], measure,
            )  # fmt: skip


def test_every_document_of_the_dossier_says_its_confidentiality() -> None:
    for path in sorted(DOSSIER.rglob("*.md")):
        head = path.read_text(encoding="utf-8")[:600]
        assert re.search(r"\*\*Confidencialidad:\*\* `(client|internal)`", head), path.name
