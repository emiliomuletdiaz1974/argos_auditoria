"""Propose a challenge for an obligation and leave it on a review branch (ARG-056).

    uv run python tools/new_challenge.py OBL-RGPD-33-2 "Texto de la obligación" [--repo .]

The tool of the normative team. It asks the local model for a proposal, runs it through the same
lint as the CI, and only if it compiles puts it on a branch `feature/reto-<id>` for an engineer to
review. It **never writes into the library of the checkout in use**: the branch is prepared in a
temporary worktree, so the jurist's working copy, index and current branch are left exactly as they
were. Nothing is pushed: publishing the branch is a human decision.
"""

import argparse
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-gateway"))

from argos_ai.backends.openai_compatible import OpenAiCompatibleBackend  # noqa: E402
from argos_ai.generate.challenge_gen import (  # noqa: E402
    ChallengeProposal,
    as_json,
    proposal_id,
    propose_challenge,
)
from argos_ai.quotas import postgres_gateway  # noqa: E402

from argos_challenges.dsl import LintContext  # noqa: E402
from argos_common.config import get_config  # noqa: E402

BRANCH_PREFIX = "feature/reto-"

__all__ = ["ChallengeProposal", "ReviewBranchError", "review_branch_for", "write_review_branch"]


class ReviewBranchError(Exception):
    """The proposal cannot be put on a review branch."""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git subcommands, no shell
        ["git", "-C", str(repo), *args],  # noqa: S607 - git from the developer's PATH
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def write_review_branch(repo: Path, challenge_id: str, family: str, text: str) -> str:
    """Commit the proposal on its own branch, from a temporary worktree. Returns the branch."""
    branch = f"{BRANCH_PREFIX}{challenge_id}"
    if _git(repo, "branch", "--list", branch):
        raise ReviewBranchError(f"the branch {branch} already exists: review it first")
    with tempfile.TemporaryDirectory(prefix="argos-reto-") as scratch:
        worktree = Path(scratch) / "worktree"
        _git(repo, "worktree", "add", "-q", "-b", branch, str(worktree), "HEAD")
        try:
            target = worktree / "library" / "challenges" / family / f"{challenge_id}.yaml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            _git(worktree, "add", str(target.relative_to(worktree)))
            _git(
                worktree,
                "commit",
                "-q",
                "-m",
                f"feat(ARG-056): propuesta de reto {challenge_id} para revisión",
            )
        finally:
            _git(repo, "worktree", "remove", "--force", str(worktree))
    return branch


def review_branch_for(repo: Path, proposal: ChallengeProposal) -> str:
    """The review branch of a proposal that compiles; an invalid one never reaches Git."""
    if not proposal.valid:
        raise ReviewBranchError(f"the proposal is not valid: {proposal.warnings}")
    challenge_id, family = proposal_id(proposal.yaml)
    return write_review_branch(repo, challenge_id, family, proposal.yaml)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("obligation")
    parser.add_argument("text")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    cfg = get_config()
    backend = OpenAiCompatibleBackend(str(cfg.LLM_LOCAL_ENDPOINT), cfg.LLM_MODEL)
    gateway = postgres_gateway(cfg.DATABASE_URL, backend, model=cfg.LLM_MODEL)
    proposal = asyncio.run(
        propose_challenge(args.obligation, args.text, gateway, LintContext.from_library())
    )
    print(as_json(proposal))
    if not proposal.valid:
        return 1
    print(f"propuesta en la rama {review_branch_for(args.repo, proposal)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
