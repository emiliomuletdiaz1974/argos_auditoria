"""Static analysis of the verdict boundary (ARG-046, F05-04).

Three rules, checked with `ast` and without importing anything:

1. only `argos_challenges.evaluator` builds a `Verdict`;
2. only `argos_challenges.store` writes `argos.verdicts`;
3. the evaluator imports no language-model package: it decides with rules, never with a model.

A star import from the evaluator is a violation by itself: it hides which names a module binds.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

EVALUATOR_MODULE = "argos_challenges.evaluator"
EVALUATOR_FILE = Path("services/challenge-engine/argos_challenges/evaluator.py")
STORE_FILE = Path("services/challenge-engine/argos_challenges/store.py")
VERDICT_TABLE = "argos.verdicts"
WRITE_KEYWORDS = ("insert into", "update", "delete from", "truncate")
AI_PACKAGES = frozenset(
    {"argos_ai", "openai", "anthropic", "llama_cpp", "vllm", "transformers", "torch"}
)
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


def _writes_verdicts(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    return VERDICT_TABLE in lowered and any(word in lowered for word in WRITE_KEYWORDS)


class _Visitor(ast.NodeVisitor):
    """Collects the names bound to the evaluator and every suspicious use of them."""

    def __init__(self, relative: str, is_evaluator: bool, is_store: bool) -> None:
        self.relative = relative
        self.is_evaluator = is_evaluator
        self.is_store = is_store
        self.violations: list[Violation] = []
        self.verdict_names: set[str] = set()
        self.module_names: set[str] = set()

    def _add(self, node: ast.AST, rule: str, detail: str) -> None:
        line = getattr(node, "lineno", 0)
        self.violations.append(Violation(self.relative, line, rule, detail))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == EVALUATOR_MODULE:
                self.module_names.add(alias.asname or alias.name.split(".")[-1])
            if self.is_evaluator and alias.name.split(".")[0] in AI_PACKAGES:
                self._add(node, "ai-import-in-evaluator", alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if self.is_evaluator and module.split(".")[0] in AI_PACKAGES:
            self._add(node, "ai-import-in-evaluator", module)
        if module == EVALUATOR_MODULE and not self.is_evaluator:
            for alias in node.names:
                if alias.name == "*":
                    self._add(node, "verdict-outside-evaluator", "star import of the evaluator")
                elif alias.name == "Verdict":
                    self.verdict_names.add(alias.asname or alias.name)
        if module == "argos_challenges" and not self.is_evaluator:
            self.module_names.update(
                alias.asname or alias.name for alias in node.names if alias.name == "evaluator"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self.is_evaluator:
            self.generic_visit(node)
            return
        func = node.func
        if isinstance(func, ast.Name) and func.id in self.verdict_names:
            self._add(node, "verdict-outside-evaluator", f"{func.id}(...)")
        if isinstance(func, ast.Attribute) and func.attr == "Verdict":
            value = func.value
            if isinstance(value, ast.Name) and value.id in self.module_names:
                self._add(node, "verdict-outside-evaluator", f"{value.id}.Verdict(...)")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and not self.is_store and _writes_verdicts(node.value):
            self._add(node, "verdict-sql-outside-store", VERDICT_TABLE)
        self.generic_visit(node)


def analyse_file(path: Path, root: Path) -> list[Violation]:
    relative = path.relative_to(root).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _Visitor(
        relative,
        is_evaluator=path == (root / EVALUATOR_FILE),
        is_store=path == (root / STORE_FILE),
    )
    visitor.visit(tree)
    return sorted(visitor.violations)


def analyse(root: Path, scan_roots: tuple[str, ...] = SCAN_ROOTS) -> list[Violation]:
    violations: list[Violation] = []
    for path in _python_files(root, scan_roots):
        violations.extend(analyse_file(path, root))
    return sorted(violations)
