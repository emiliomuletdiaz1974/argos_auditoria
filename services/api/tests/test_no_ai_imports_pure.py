"""ADR-0012 · the API talks to the AI layer over HTTP and never imports it.

What the model says is handled inside the gateway's perimeter. If a module of the API imported
`argos_ai`, the model's output would be processed in the same process that can write a verdict.
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "argos_api"


def _imported(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _is_ai(module: str) -> bool:
    """The package `argos_ai` or one of its modules; `argos_airgap` only shares the letters."""
    return module == "argos_ai" or module.startswith("argos_ai.")


def test_the_check_matches_the_package_and_not_its_prefix() -> None:
    assert _is_ai("argos_ai") and _is_ai("argos_ai.guardrails")
    assert not _is_ai("argos_airgap") and not _is_ai("argos_airgap.importers")


def test_no_module_of_the_api_imports_the_ai_layer() -> None:
    offenders = {
        str(path.relative_to(PACKAGE)): sorted(n for n in _imported(path) if _is_ai(n))
        for path in PACKAGE.rglob("*.py")
    }
    assert {name: found for name, found in offenders.items() if found} == {}
