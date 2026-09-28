"""ARG-095 · assisted failover of the size M: a person decides, this does it (F10-09, RB-07).

    python platform/ha/size-m/failover.py --primary-dsn <dsn> --replica-dsn <dsn> [--confirm]

Without --confirm it is a drill: it checks and says what it would do, and changes nothing. With
it, and only when the checks pass, it promotes the replica. There is no automatic failover in
size M: two primaries writing evidence would be two truths, worse than ten minutes of downtime.

1. The primary must not answer. If it does, the script aborts: promoting would split the brain.
   An answer that refuses us (a password, a database that is not there) is an answer: only a
   primary that cannot be reached counts as down (quality review QA-080).
2. The replica must be a standby. Its replay lag is shown; beyond --max-lag it warns that the last
   transactions of the primary may be lost. A replica that never replayed anything has an unknown
   lag, said as such, not zero.
3. It promotes the replica and waits for the promotion; a promotion that did not happen in time
   stops the failover.
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
    """Whether the server answers. A refusal of the server itself (it carries a SQLSTATE: a
    password, a missing database) is an answer; only a server that cannot be reached is not."""
    try:
        with psycopg.connect(dsn, connect_timeout=TIMEOUT) as conn:
            conn.execute("SELECT 1")
    except psycopg.OperationalError as failure:
        return failure.sqlstate is not None
    return True


def standby_lag(dsn: str) -> tuple[bool, int | None]:
    """Whether the node is a standby, and its replay lag in whole seconds; None when it never
    replayed a transaction, which is not a lag of zero."""
    with psycopg.connect(dsn, connect_timeout=TIMEOUT) as conn:
        row = conn.execute(
            "SELECT pg_is_in_recovery(),"
            " extract(epoch FROM now() - pg_last_xact_replay_timestamp())"
        ).fetchone()
    if row is None:
        raise RuntimeError("the replica did not answer its state")
    lag = None if row[1] is None else int(round(float(row[1])))
    return bool(row[0]), lag


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
    if lag is None:
        print("WARNING: the replica never replayed a transaction: its lag is unknown.")
    else:
        print(f"      replay lag: {lag} s")
        if lag > args.max_lag:
            print(f"WARNING: lag above {args.max_lag} s: the last transactions may be lost.")
    if not args.confirm:
        print("Drill OK: nothing was changed. Run it again with --confirm to promote.")
        return 0

    print("[3/5] promoting the replica")
    with psycopg.connect(args.replica_dsn, autocommit=True) as conn:
        promoted = conn.execute("SELECT pg_promote(true, 60)").fetchone()
    if not promoted or not promoted[0]:
        print("ERROR: the replica was not promoted within 60 s. Nothing else was done: RB-07.")
        return 3
    print("[4/5] verifying the journal on the promoted node")
    journal = PostgresJournal(args.replica_dsn)
    if not journal.verify().intact:
        print("CRITICAL: the journal does not verify after the promotion. Do not go on: RB-01.")
        return 3
    print("[5/5] recording the failover")
    host = urlparse(args.replica_dsn).hostname or "replica"
    accepted = "unknown" if lag is None else lag
    seq = journal.append(ACTOR, "ha.failover", {"promoted": host, "lag_seconds": accepted})
    print(f"FAILOVER DONE (journal entry {seq}). Point the clients at the promoted node.")
    print("The old primary must not start its services: bring it back with rejoin.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
