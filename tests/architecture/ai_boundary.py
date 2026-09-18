"""Static analysis of the AI boundary (ARG-052, F06-01).

The Phase 06 promise is not a paragraph in a document: **no path of code goes from the language
model to the emission of a verdict**. This module checks the half that lives in the source tree,
following the real import graph, so a cable tied three modules away is caught too.

Two rules:

1. nothing reachable from `services/ai-gateway/` imports the modules that decide or write a
   verdict (`argos_challenges.evaluator`, `.store`, `.findings`), directly or transitively;
2. no module of the gateway writes the tables of the verdict either, whatever route it took;
   its tests are exempt from this second rule, because proving a rejection means quoting the
   sentence that gets rejected — but not from the first one.

The other two halves of the barrier are checked where they live: the network from inside the
container (F06-13) and the database privileges against a real server (`tests/integration`).
"""

import ast
from collections import deque
from dataclasses import dataclass
from pathlib import Path

GATEWAY_ROOT = "services/ai-gateway"
FORBIDDEN_MODULES = frozenset(
    {
        "argos_challenges.evaluator",
        "argos_challenges.store",
        "argos_challenges.findings",
    }
)
VERDICT_TABLES = ("argos.verdicts", "argos.findings")
WRITE_KEYWORDS = ("insert into", "update", "delete from", "truncate")
SCAN_ROOTS = ("libs", "connectors", "services", "tools")


@dataclass(frozen=True, slots=True, order=True)
class Violation:
    path: str
    line: int
    rule: str
    detail: str


def _python_files(root: Path, scan_roots: tuple[str, ...] = SCAN_ROOTS) -> list[Path]:
    files: list[Path] = []
    for name in scan_roots:
        base = root / name
        if base.is_dir():
            files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def module_name(path: Path, root: Path) -> str:
    """The importable name of a file, cutting the workspace layout off its head.

    `services/ai-gateway/argos_ai/rag/pipeline.py` is imported as `argos_ai.rag.pipeline`: the
    member directory is not part of the name, the package inside it is.
    """
    parts = list(path.relative_to(root).with_suffix("").parts)
    for index in range(len(parts)):
        if (root.joinpath(*parts[: index + 1], "__init__.py")).is_file():
            parts = parts[index:]
            break
    else:
        parts = parts[-1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports_of(tree: ast.AST, own_module: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # a relative import stays inside its own package
                package = own_module.rsplit(".", node.level)[0] if "." in own_module else own_module
                base = f"{package}.{node.module}" if node.module else package
            else:
                base = node.module or ""
            if base:
                found.add(base)
                found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def _is_test(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def _write_lines(tree: ast.AST) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = " ".join(node.value.lower().split())
            for table in VERDICT_TABLES:
                if table in lowered and any(word in lowered for word in WRITE_KEYWORDS):
                    lines.append((node.lineno, table))
    return lines


def import_graph(root: Path, scan_roots: tuple[str, ...] = SCAN_ROOTS) -> dict[str, set[str]]:
    """Module -> modules it imports, for every file of the workspace."""
    graph: dict[str, set[str]] = {}
    for path in _python_files(root, scan_roots):
        name = module_name(path, root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        graph.setdefault(name, set()).update(_imports_of(tree, name))
    return graph


def _route(graph: dict[str, set[str]], start: str) -> list[str] | None:
    """The shortest import route from a module to a forbidden one, or None."""
    queue: deque[list[str]] = deque([[start]])
    seen = {start}
    while queue:
        route = queue.popleft()
        for target in sorted(graph.get(route[-1], ())):
            if target in FORBIDDEN_MODULES:
                return [*route, target]
            if target in graph and target not in seen:
                seen.add(target)
                queue.append([*route, target])
    return None


def analyse(root: Path, scan_roots: tuple[str, ...] = SCAN_ROOTS) -> list[Violation]:
    """Every breach of the barrier, sorted, with the route that tied the cable."""
    graph = import_graph(root, scan_roots)
    violations: list[Violation] = []
    for path in _python_files(root, scan_roots):
        relative = path.relative_to(root).as_posix()
        if not relative.startswith(f"{GATEWAY_ROOT}/"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        name = module_name(path, root)
        for target in sorted(_imports_of(tree, name) & FORBIDDEN_MODULES):
            violations.append(Violation(relative, 0, "ai-imports-the-verdict", target))
        route = _route(graph, name)
        if route is not None and len(route) > 2:
            violations.append(Violation(relative, 0, "ai-reaches-the-verdict", " -> ".join(route)))
        if not _is_test(path):
            # A test of the guardrails has to quote the forbidden sentence to prove it is
            # rejected. Quoting it is not tying the cable, and tests do not ship; what a test
            # may not do is import the verdict modules, and that rule does apply above.
            for line, table in _write_lines(tree):
                violations.append(Violation(relative, line, "ai-writes-the-verdict", table))
    return sorted(violations)
