"""Settings of the repository that a careless edit would weaken without any test noticing."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _yaml(relative: str) -> Any:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def test_the_ci_token_can_only_read_the_repository() -> None:
    # Without a declaration the token gets the repository default, which may allow writing.
    workflow = _yaml(".github/workflows/ci.yml")
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        assert "permissions" not in job or job["permissions"] == {"contents": "read"}, name


def test_anonymous_grafana_in_development_can_only_look() -> None:
    grafana = _yaml("deploy/dev/compose.yaml")["services"]["grafana"]["environment"]
    assert grafana.get("GF_AUTH_ANONYMOUS_ORG_ROLE") == "Viewer"


def test_a_push_runs_only_the_checks_that_work_on_a_clean_runner() -> None:
    """The integration suite needs the whole environment of `make dev` (37 containers): it runs on
    the developer's machine with `make check`, and in the CI only when asked for by hand."""
    workflow = _yaml(".github/workflows/ci.yml")
    triggers = workflow.get("on", workflow.get(True))
    assert "workflow_dispatch" in triggers
    for name in ("integration", "build"):
        assert workflow["jobs"][name]["if"] == "github.event_name == 'workflow_dispatch'", name
    assert "if" not in workflow["jobs"]["verify"], "verify runs on every push"
