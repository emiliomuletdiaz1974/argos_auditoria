"""argos-update apply|verify|recover|watch (ARG-086, F09-10).

    argos-update verify BUNDLE                 everything checked, nothing touched
    argos-update apply BUNDLE [--allow-downgrade]
    argos-update recover                       takes an interrupted update back (run at start)
    argos-update watch                         applies the requests the API queued, one by one

Configuration (environment):
    ARGOS_UPDATE_STATE          state folder: installed version and reverse plan
                                (default /var/lib/argos/update)
    ARGOS_RELEASE_PUBLIC_KEY    the pinned release key (default /etc/argos/keys/release.pub);
                                never read from the bundle
    ARGOS_CONTENT_PUBLIC_KEY    the pinned content key (ARG-040), for bundles with content
    ARGOS_COMPOSE_FILE          development: drive Docker Compose; without it, Kubernetes
    ARGOS_NAMESPACE             Kubernetes namespace (default argos-services)
    ARGOS_DATABASE_URL          journal, security log and migrations
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from argos_common import security_log
from argos_common.journal_pg import PostgresJournal
from argos_common.migrations import apply_migrations

from . import Orchestrator, Updater, UpdateRejectedError
from .orchestrator import ComposeOrchestrator, KubernetesOrchestrator

ACTOR = "system:updater"
# Which services run each image of the release.
SERVICES: dict[str, list[str]] = {
    "argos-api": ["api", "webhook-worker"],
    "argos-challenge-engine": ["challenge-worker"],
    "argos-evidence": ["evidence-worker", "evidence-api"],
    "argos-ai-gateway": ["ai-gateway"],
    "argos-example": ["example"],
    "argos-verifier": ["verifier"],
}


def recorder(dsn: str | None) -> Any:
    """Each step to the journal (what the product did) and to the security log (who changed it)."""

    def record(kind: str, outcome: str, detail: Mapping[str, Any]) -> None:
        print(f"{kind} {outcome} {json.dumps(dict(detail), ensure_ascii=False)}")
        if not dsn:
            return
        PostgresJournal(dsn).append(ACTOR, kind, dict(detail))
        security_log.log(dsn).record(
            kind,
            ACTOR,
            outcome,
            {
                k: v if isinstance(v, str | int | bool) or v is None else str(v)
                for k, v in detail.items()
            },
            source="argos-updater",
        )

    return record


def orchestrator() -> Orchestrator:
    compose = os.environ.get("ARGOS_COMPOSE_FILE")
    if compose:
        return ComposeOrchestrator(Path(compose))
    return KubernetesOrchestrator(os.environ.get("ARGOS_NAMESPACE", "argos-services"))


def _migrator(dsn: str | None) -> Callable[[Path], None] | None:
    """Migrations of the bundle: expand-contract, so the previous code runs on the new schema."""
    if not dsn:
        return None

    def migrate(folder: Path) -> None:
        apply_migrations(dsn, folder)

    return migrate


def build_updater() -> Updater:
    state = Path(os.environ.get("ARGOS_UPDATE_STATE", "/var/lib/argos/update"))
    state.mkdir(parents=True, exist_ok=True)
    key = Path(os.environ.get("ARGOS_RELEASE_PUBLIC_KEY", "/etc/argos/keys/release.pub"))
    content = os.environ.get("ARGOS_CONTENT_PUBLIC_KEY")
    dsn = os.environ.get("ARGOS_DATABASE_URL")
    return Updater(
        state_dir=state,
        public_key=key.read_bytes(),
        orchestrator=orchestrator(),
        services=SERVICES,
        record=recorder(dsn),
        migrate=_migrator(dsn),
        content_key=Path(content).read_bytes() if content else None,
    )


def watch(updater: Updater, inbox: Path, queue: Path, interval: float) -> None:
    """Apply what the API queued (POST /api/v1/system/updates), oldest first, one at a time.

    A request names a bundle of the inbox, never a path: the API sees its own folders.
    """
    while True:
        for request in sorted(queue.glob("*.json")):
            wanted = json.loads(request.read_text(encoding="utf-8"))
            request.unlink()
            try:
                bundle = inbox / Path(str(wanted["bundle"])).name
                updater.apply(bundle, bool(wanted.get("allow_downgrade")))
            except UpdateRejectedError as refused:
                print(f"update refused: {refused}", file=sys.stderr)
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="argos-update", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    apply = commands.add_parser("apply")
    apply.add_argument("bundle", type=Path)
    apply.add_argument("--allow-downgrade", action="store_true")
    commands.add_parser("recover")
    watching = commands.add_parser("watch")
    watching.add_argument("--inbox", type=Path, default=Path("/var/lib/argos/update/inbox"))
    watching.add_argument("--queue", type=Path, default=Path("/var/lib/argos/update/queue"))
    watching.add_argument("--interval", type=float, default=10.0)
    args = parser.parse_args(argv)

    updater = build_updater()
    try:
        if args.command == "verify":
            print(f"bundle {updater.verify(args.bundle).version} verified")
        elif args.command == "apply":
            updater.recover()
            print(f"updated to {updater.apply(args.bundle, args.allow_downgrade)}")
        elif args.command == "recover":
            print("recovered" if updater.recover() else "nothing to recover")
        else:
            updater.recover()
            watch(updater, args.inbox, args.queue, args.interval)
    except UpdateRejectedError as refused:
        print(f"update refused: {refused}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
