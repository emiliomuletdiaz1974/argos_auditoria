"""ARG-095 · bring an old primary back as a replica of the new one (F10-09, RB-07).

    python platform/ha/size-m/rejoin.py --node ha-node-a --node-dsn <dsn>
        --primary ha-node-b --primary-dsn <dsn> --compose-file deploy/dev/compose.yaml

After a failover the old primary has transactions the new one never saw, and it must never start
as a primary again. This clones it again from the new primary: its data is emptied and it starts
as a physical standby with its own slot. It refuses when the node is still running as a primary
(stop it first) and when the node given as primary is not one.

The nodes of the development environment are containers of the profile `ha`; `ComposeNodes` is
how this script drives them. On the appliance the same steps run on its orchestrator (F10-92).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import psycopg

from argos_common.journal_pg import PostgresJournal

ACTOR = "system:ha"
TIMEOUT = 3
WAIT_SECONDS = 180


def role_of(dsn: str) -> str:
    """'primary', 'standby', or 'down'."""
    try:
        with psycopg.connect(dsn, connect_timeout=TIMEOUT) as conn:
            row = conn.execute("SELECT pg_is_in_recovery()").fetchone()
    except psycopg.OperationalError:
        return "down"
    return "standby" if row and row[0] else "primary"


class ComposeNodes:
    """The two nodes of the profile `ha` of the development compose."""

    VOLUMES = {"ha-node-a": "argos-dev_ha-a-data", "ha-node-b": "argos-dev_ha-b-data"}
    PRIMARY_VARIABLES = {"ha-node-a": "HA_A_PRIMARY", "ha-node-b": "HA_B_PRIMARY"}

    def __init__(self, compose_file: str) -> None:
        self._compose = ["docker", "compose", "-f", compose_file, "--profile", "ha"]

    def _run(self, command: list[str], env: dict[str, str] | None = None) -> None:
        subprocess.run(  # noqa: S603 - fixed commands with arguments as a list
            command,
            check=True,
            capture_output=True,
            timeout=600,
            env={**os.environ, **(env or {})},
        )

    def reclone(self, node: str, primary: str) -> None:
        self._run([*self._compose, "rm", "-sf", node])
        self._run(["docker", "volume", "rm", "-f", self.VOLUMES[node]])  # noqa: S607
        self._run([*self._compose, "up", "-d", node], env={self.PRIMARY_VARIABLES[node]: primary})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--node", required=True, help="the old primary")
    parser.add_argument("--node-dsn", required=True)
    parser.add_argument("--primary", required=True, help="the new primary, as the node reaches it")
    parser.add_argument("--primary-dsn", required=True)
    parser.add_argument("--compose-file", required=True)
    args = parser.parse_args(argv)

    print("[1/4] the new primary must be a primary")
    if role_of(args.primary_dsn) != "primary":
        print("ERROR: the node given as primary is not one. Nothing was changed.")
        return 2
    print("[2/4] the old primary must not be running as a primary")
    if role_of(args.node_dsn) == "primary":
        print("ERROR: the old primary still runs as a primary. Stop it first: two primaries.")
        return 1
    print("[3/4] cloning the node again from the new primary")
    ComposeNodes(args.compose_file).reclone(args.node, args.primary)
    deadline = time.monotonic() + WAIT_SECONDS
    while role_of(args.node_dsn) != "standby":
        if time.monotonic() > deadline:
            print("ERROR: the node did not come back as a standby in time.")
            return 3
        time.sleep(2)
    print("[4/4] recording the rejoin")
    seq = PostgresJournal(args.primary_dsn).append(
        ACTOR, "ha.rejoin", {"node": args.node, "primary": args.primary}
    )
    print(f"REJOIN DONE (journal entry {seq}): {args.node} is a replica of {args.primary}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
