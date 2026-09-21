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


def test_no_module_of_the_api_imports_the_ai_layer() -> None:
    offenders = {
        str(path.relative_to(PACKAGE)): sorted(
            n for n in _imported(path) if n.startswith("argos_ai")
        )
        for path in PACKAGE.rglob("*.py")
    }
    assert {name: found for name, found in offenders.items() if found} == {}
