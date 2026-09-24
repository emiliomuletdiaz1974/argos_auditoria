"""argos-support collect|watch|package (ARG-088, F09-11).

    argos-support collect OUT            a preview in OUT, to read before anything leaves
    argos-support watch --store DIR      collects the requests the API queued, one by one
    argos-support package PREVIEW --approve SHA256 --recipient FILE --out FILE
                                         encrypts the reviewed preview for support

It runs next to the orchestrator: on the host in development (like the updater, note ARG-086),
on the node in the appliance.

Configuration (environment):
    ARGOS_COMPOSE_FILE     development: read Docker Compose; without it, Kubernetes
    ARGOS_NAMESPACE        Kubernetes namespace (default argos-services)
    ARGOS_DATABASE_URL     the tail of the journal (sequence, actor, action, date)
    ARGOS_UPDATE_STATE     the folder with the installed version (default /var/lib/argos/update)
"""

import argparse
import datetime as dt
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg

from argos_common import security_log
from argos_common.journal_pg import PostgresJournal

from . import (
    DiagnosticsError,
    DiagnosticsStore,
    Inspector,
    JournalTail,
    Preview,
    build_package,
    collect,
)
from .inspectors import ComposeInspector, KubernetesInspector

ACTOR = "system:support"
_TAIL = "SELECT seq, actor, action, at FROM argos.audit_journal ORDER BY seq DESC LIMIT %s"


def postgres_journal_tail(dsn: str | None) -> JournalTail:
    """The last entries of the journal, without their payload. No DSN: an empty tail."""

    def tail(entries: int) -> Sequence[Mapping[str, Any]]:
        if not dsn:
            return []
        with psycopg.connect(dsn) as conn:
            rows = conn.execute(_TAIL, (entries,)).fetchall()
        return [
            {"seq": seq, "actor": actor, "action": action,
             "at": at.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
            for seq, actor, action, at in rows
        ]  # fmt: skip

    return tail


def inspector() -> Inspector:
    compose = os.environ.get("ARGOS_COMPOSE_FILE")
    if compose:
        return ComposeInspector(Path(compose))
    return KubernetesInspector(os.environ.get("ARGOS_NAMESPACE", "argos-services"))


def installed_version() -> str | None:
    path = Path(os.environ.get("ARGOS_UPDATE_STATE", "/var/lib/argos/update")) / "version"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def gather() -> Preview:
    dsn = os.environ.get("ARGOS_DATABASE_URL")
    return collect(
        inspector(), postgres_journal_tail(dsn), installed_version(), dt.datetime.now(dt.UTC)
    )


def _record(action: str, detail: dict[str, Any]) -> None:
    dsn = os.environ.get("ARGOS_DATABASE_URL")
    if not dsn:
        return
    PostgresJournal(dsn).append(ACTOR, action, detail)
    security_log.log(dsn).record(action, ACTOR, "succeeded", detail, source="argos-support")


def watch(store: DiagnosticsStore, interval: float, once: bool = False) -> None:
    """Collect every request the API queued, oldest first."""
    while True:
        for ident in store.pending():
            preview = gather()
            store.save(ident, preview)
            _record("support.preview_collected", {"id": ident, "index": preview.index_sha256})
            print(f"preview {ident} ready, index {preview.index_sha256}")
        if once:
            return
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="argos-support", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    collecting = commands.add_parser("collect")
    collecting.add_argument("out", type=Path)
    watching = commands.add_parser("watch")
    watching.add_argument("--store", type=Path, default=Path("/var/lib/argos/support"))
    watching.add_argument("--interval", type=float, default=5.0)
    watching.add_argument("--once", action="store_true")
    packaging = commands.add_parser("package")
    packaging.add_argument("preview", type=Path)
    packaging.add_argument("--approve", required=True, help="SHA-256 of the INDEX.json you read")
    packaging.add_argument("--recipient", type=Path, required=True, help="age key of support")
    packaging.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "collect":
            store = DiagnosticsStore(args.out)
            ident = store.request(ACTOR)
            store.save(ident, gather())
            print(f"preview in {store.previews / ident}; read it, then `argos-support package`")
        elif args.command == "watch":
            watch(DiagnosticsStore(args.store), args.interval, args.once)
        else:
            folder: Path = args.preview
            preview = DiagnosticsStore(folder.parent.parent).load(folder.name)
            recipient = args.recipient.read_text(encoding="utf-8")
            args.out.write_bytes(build_package(preview, args.approve, recipient))
            _record("support.package_built", {"id": folder.name, "index": args.approve})
            print(f"package for support in {args.out}")
    except DiagnosticsError as refused:
        print(f"diagnostics refused: {refused}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
