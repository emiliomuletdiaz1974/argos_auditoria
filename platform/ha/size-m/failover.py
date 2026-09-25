"""ARG-095 · assisted failover of the size M: a person decides, this does it (F10-09, RB-07).

    python platform/ha/size-m/failover.py --primary-dsn <dsn> --replica-dsn <dsn> [--confirm]

Without --confirm it is a drill: it checks and says what it would do, and changes nothing. With
it, and only when the checks pass, it promotes the replica. There is no automatic failover in
size M: two primaries writing evidence would be two truths, worse than ten minutes of downtime.

1. The primary must not answer. If it does, the script aborts: promoting would split the brain.
2. The replica must be a standby. Its replay lag is shown; beyond --max-lag it warns that the last
   transactions of the primary may be lost.
3. It promotes the replica and waits for the promotion.
4. It verifies the journal on the promoted node before anything else writes to it. A journal that
   does not verify stops the failover here: RB-01.
5. It records `ha.failover` in the journal, with the node and the lag accepted.
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

import psycopg

from argos_common.journal_pg import PostgresJournal

ACTOR = "system:ha"
TIMEOUT = 3


def answers(dsn: str) -> bool:
    try:
        with psycopg.connect(dsn, connect_timeout=TIMEOUT) as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError:
        return False
    return True


def standby_lag(dsn: str) -> tuple[bool, int]:
    """Whether the node is a standby, and its replay lag in whole seconds."""
    with psycopg.connect(dsn, connect_timeout=TIMEOUT) as conn:
        row = conn.execute(
            "SELECT pg_is_in_recovery(),"
            " coalesce(extract(epoch FROM now() - pg_last_xact_replay_timestamp()), 0)"
        ).fetchone()
    if row is None:
        raise RuntimeError("the replica did not answer its state")
    return bool(row[0]), int(round(float(row[1])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--primary-dsn", required=True)
    parser.add_argument("--replica-dsn", required=True)
    parser.add_argument("--confirm", action="store_true", help="promote; without it, a drill")
    parser.add_argument("--max-lag", type=int, default=300, help="seconds of lag before warning")
    args = parser.parse_args(argv)

    print("[1/5] the primary must be down")
    if answers(args.primary_dsn):
        print("ERROR: the primary answers. Aborting: promoting now would make two primaries.")
        return 1
    print("[2/5] the state of the replica")
    if not answers(args.replica_dsn):
        print("ERROR: the replica does not answer either.")
        return 2
    standby, lag = standby_lag(args.replica_dsn)
    if not standby:
        print("ERROR: the replica is not a standby: it is already a primary.")
        return 2
    print(f"      replay lag: {lag} s")
    if lag > args.max_lag:
        print(f"WARNING: lag above {args.max_lag} s: the last transactions may be lost.")
    if not args.confirm:
        print("Drill OK: nothing was changed. Run it again with --confirm to promote.")
        return 0

    print("[3/5] promoting the replica")
    with psycopg.connect(args.replica_dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_promote(true, 60)")
    print("[4/5] verifying the journal on the promoted node")
    journal = PostgresJournal(args.replica_dsn)
    if not journal.verify().intact:
        print("CRITICAL: the journal does not verify after the promotion. Do not go on: RB-01.")
        return 3
    print("[5/5] recording the failover")
    host = urlparse(args.replica_dsn).hostname or "replica"
    seq = journal.append(ACTOR, "ha.failover", {"promoted": host, "lag_seconds": lag})
    print(f"FAILOVER DONE (journal entry {seq}). Point the clients at the promoted node.")
    print("The old primary must not start its services: bring it back with rejoin.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
