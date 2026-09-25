"""ARG-099 · the book of operation: every alert has its runbook, each one usable (F10-06).

A runbook lives in docs/operacion/runbooks/RB-NN-<name>.md with a header that says which alerts it
answers, or that it is a procedure. The tests keep it honest:

- every alert of every rule file points at an existing runbook, and that runbook lists it;
- every runbook answers some alert, or is a procedure;
- every runbook has the five sections, in order: symptom, diagnosis, action, verification and
  when to escalate;
- every command a runbook asks to run exists in the repository: a `make` target, a tool, a CLI.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
RUNBOOKS = REPO / "docs" / "operacion" / "runbooks"
RULE_FILES = [
    REPO / "platform" / "observability" / "rules" / "argos.rules.yml",
    REPO / "deploy" / "dev" / "prometheus" / "rules" / "security.yml",
    REPO / "deploy" / "dev" / "prometheus" / "rules" / "backup.yml",
]
SECTIONS = ["## Síntoma", "## Diagnóstico", "## Acción", "## Verificación", "## Cuándo escalar"]


def _runbooks() -> dict[str, tuple[dict[str, Any], str]]:
    found = {}
    for path in sorted(RUNBOOKS.glob("RB-*.md")):
        text = path.read_text(encoding="utf-8")
        header, body = text.split("---\n", 2)[1:]
        found[path.name] = (dict(yaml.safe_load(header)), body)
    return found


def _alerts() -> dict[str, str]:
    """Every alert and the runbook it points at."""
    alerts = {}
    for path in RULE_FILES:
        for group in yaml.safe_load(path.read_text(encoding="utf-8"))["groups"]:
            for rule in group["rules"]:
                alerts[rule["alert"]] = rule["annotations"]["runbook_url"]
    return alerts


def test_there_are_twelve_runbooks_numbered_in_order() -> None:
    names = list(_runbooks())
    assert [n[:5] for n in names] == [f"RB-{i:02d}" for i in range(1, 13)]


def test_every_alert_points_at_a_runbook_that_lists_it() -> None:
    runbooks = _runbooks()
    for alert, url in _alerts().items():
        name = Path(url).name
        assert url == f"docs/operacion/runbooks/{name}", alert
        assert name in runbooks, (alert, url)
        assert alert in runbooks[name][0].get("alerts", []), (alert, name)


def test_every_runbook_answers_an_alert_or_is_a_procedure() -> None:
    alerts = _alerts()
    for name, (header, _) in _runbooks().items():
        listed = header.get("alerts", [])
        assert listed or header.get("procedure") is True, name
        for alert in listed:
            assert alerts.get(alert, "").endswith(name), (name, alert)


@pytest.mark.parametrize("name", sorted(p.name for p in RUNBOOKS.glob("RB-*.md")))
def test_every_runbook_has_the_five_sections_in_order(name: str) -> None:
    body = _runbooks()[name][1]
    positions = [body.find(section) for section in SECTIONS]
    assert all(p >= 0 for p in positions), (name, dict(zip(SECTIONS, positions, strict=True)))
    assert positions == sorted(positions), name


def _commands(body: str) -> list[str]:
    blocks = re.findall(r"```bash\n(.*?)```", body, re.S)
    return [line.strip() for block in blocks for line in block.splitlines() if line.strip()]


def _makefile_targets() -> set[str]:
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"^([a-z][a-z0-9-]*):", text, re.M))


def _clis() -> set[str]:
    names: set[str] = set()
    for path in REPO.glob("services/*/pyproject.toml"):
        text = path.read_text(encoding="utf-8")
        names |= set(re.findall(r"^(argos-[a-z-]+)\s*=", text, re.M))
    return names


@pytest.mark.parametrize("name", sorted(p.name for p in RUNBOOKS.glob("RB-*.md")))
def test_every_command_of_a_runbook_exists(name: str) -> None:
    targets, clis = _makefile_targets(), _clis()
    for command in _commands(_runbooks()[name][1]):
        words = command.split()
        if words[0] == "make":
            assert words[1] in targets, (name, command)
        elif words[:3] == ["uv", "run", "python"]:
            assert (REPO / words[3]).is_file(), (name, command)
        elif words[0].startswith("argos-"):
            assert words[0] in clis, (name, command)
        else:
            assert words[0] in {"docker", "curl", "psql"}, (name, command)
