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
