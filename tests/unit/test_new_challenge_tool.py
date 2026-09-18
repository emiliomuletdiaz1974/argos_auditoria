"""ARG-056 · a proposal enters Git as a review branch, never straight into the library (F06-09).

Run against a throwaway repository: the tool must leave the checkout the jurist is working on
exactly as it was, and put the proposal on its own branch for an engineer to review.
"""

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).parents[2] / "tools" / "new_challenge.py"
PROPOSAL = "id: sec-encryption-in-transit\nversion: '1.0'\n"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("new_challenge", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed git subcommands on a throwaway repo
        ["git", "-C", str(repo), *args],  # noqa: S607 - git from the developer's PATH
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "dev@example.invalid")
    _git(tmp_path, "config", "user.name", "Dev")
    (tmp_path / "README.md").write_text("repo\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "inicio")
    return tmp_path


def test_the_proposal_lands_on_its_own_branch(repo: Path) -> None:
    branch = _tool().write_review_branch(repo, "sec-encryption-in-transit", "sec", PROPOSAL)
    assert branch == "feature/reto-sec-encryption-in-transit"
    shown = _git(repo, "show", f"{branch}:library/challenges/sec/sec-encryption-in-transit.yaml")
    assert shown == PROPOSAL.strip()


def test_the_checkout_of_the_jurist_is_left_untouched(repo: Path) -> None:
    """Not a new file, not a branch switch: the library in use never sees the proposal."""
    _tool().write_review_branch(repo, "sec-encryption-in-transit", "sec", PROPOSAL)
    assert _git(repo, "branch", "--show-current") == "main"
    assert not (repo / "library").exists()
    assert _git(repo, "status", "--porcelain") == ""


def test_the_commit_is_plain_and_says_it_is_a_proposal(repo: Path) -> None:
    branch = _tool().write_review_branch(repo, "sec-encryption-in-transit", "sec", PROPOSAL)
    message = _git(repo, "log", "-1", "--format=%B", branch)
    assert message.startswith("feat(ARG-056): propuesta de reto sec-encryption-in-transit")
    assert "Co-Authored-By" not in message


def test_an_existing_branch_is_not_overwritten(repo: Path) -> None:
    """A second proposal for the same id must not bury the first one before it is reviewed."""
    tool = _tool()
    tool.write_review_branch(repo, "sec-encryption-in-transit", "sec", PROPOSAL)
    with pytest.raises(tool.ReviewBranchError, match="already exists"):
        tool.write_review_branch(repo, "sec-encryption-in-transit", "sec", "id: otra\n")


def test_an_invalid_proposal_never_reaches_git(repo: Path) -> None:
    tool = _tool()
    with pytest.raises(tool.ReviewBranchError, match="not valid"):
        tool.review_branch_for(repo, tool.ChallengeProposal("", False, "a" * 64, ["x"]))
    assert _git(repo, "branch", "--list", "feature/reto-*") == ""
