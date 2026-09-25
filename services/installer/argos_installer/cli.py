"""`argos-install`: the installer of week 1 from the console of the appliance (ARG-096).

    argos-install --config installer.yaml [--dry-run] [--state-dir /var/lib/argos/install]
    argos-install --prerequisites M [--sizes sizes.yaml]   # the list before shipping (ARG-097)

The report is signed with the release key of Vault transit (`ARGOS_VAULT_ADDR`, and the token in
the file `ARGOS_INSTALL_VAULT_TOKEN_FILE`, never in a variable) and recorded in the journal
(`ARGOS_DATABASE_URL`). A dry run needs neither: it only prints what it would run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import SIZES_FILE, Installer, load_config, subprocess_runner

DEFAULT_STATE = Path("/var/lib/argos/install")


class _NoSigner:
    def sign(self, data: bytes) -> bytes:
        raise RuntimeError("a dry run signs nothing")

    def public_key(self) -> bytes:
        raise RuntimeError("a dry run signs nothing")


def _signer() -> Any:
    from argos_common.release import VaultTransitSigner

    token = Path(os.environ["ARGOS_INSTALL_VAULT_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    return VaultTransitSigner(os.environ.get("ARGOS_VAULT_ADDR", "http://127.0.0.1:8200"), token)


def _record(actor: str, action: str, payload: dict[str, Any]) -> object:
    from argos_common.journal_pg import PostgresJournal

    return PostgresJournal(os.environ["ARGOS_DATABASE_URL"]).append(actor, action, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="argos-install", description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--prerequisites", choices=("S", "M", "L"), help="the list before shipping")
    parser.add_argument("--sizes", type=Path, default=Path(SIZES_FILE))
    parser.add_argument("--dry-run", action="store_true", help="print the commands, run none")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.prerequisites:
        from .site_check import prerequisites

        print(f"Lista previa de la sala para la talla {args.prerequisites}:")
        for item in prerequisites(args.sizes, args.prerequisites):
            print(f"  [ ] {item['item']}: {item['criterion']}")
        return 0
    if args.config is None:
        parser.error("--config is required to install")
    config = load_config(args.config)
    installer = Installer(
        config,
        subprocess_runner,
        state_dir=args.state_dir,
        signer=_NoSigner() if args.dry_run else _signer(),
        record=(lambda *entry: None) if args.dry_run else _record,
        dry_run=args.dry_run,
    )
    report = installer.run()
    for step in report["steps"]:
        if args.dry_run:
            print(f"[{step['key']}] {step['title']}")
            for command in step["would_run"]:
                print("    " + json.dumps(command, ensure_ascii=False))
        else:
            mark = "OK " if step["ok"] else "NO "
            print(f"{mark}[{step['key']}] {step['title']}: {step['detail']}")
    if args.dry_run:
        print("Dry run: nothing was changed.")
        return 0
    if report["completed"]:
        print(f"Installation completed; signed report in {args.state_dir}.")
        return 0
    print("Stopped: fix the step marked NO and run argos-install again; it resumes there.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
