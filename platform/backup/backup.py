"""ARG-089 · the daily backup: three sets, encrypted end to end by restic (F09-12).

    uv run python platform/backup/backup.py [--repository PATH|URL]

- `db`: `pg_dump -Fc` of the database and the roles without their passwords
  (`pg_dumpall --roles-only --no-role-passwords`), with an ephemeral login user of the read-only
  role `svc_backup` that Vault creates for the run and revokes after it;
- `evidence`: the WORM store, read-only;
- `config`: the secrets of `argos/` in Vault, the compose file and the state of its services.
  (On the appliance: `vault operator raft snapshot` and the manifests of k3s; the development Vault
  keeps its state in memory and has no snapshot.)

Then retention (14 daily, 8 weekly, 12 monthly) and `restic check` over a rotating 5 % of the data.
The run goes to the journal and the security log. The dump is written in a working folder that is
removed when the run ends, also on failure.

It runs where Docker is: on the host in development, like the updater (note ARG-086), and on the
node of the appliance, with the repository of the client (`s3:…` or `sftp:…`).
"""

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import backup_common as common
from restore_test import PostgresProduction, workspace

from argos_common import security_log
from argos_common.journal_pg import PostgresJournal

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "dev" / "compose.yaml"
EVIDENCE_VOLUME = "argos-dev_evidence-data"
# Verified TLS inside the container too: the internal CA it already has (F09-06).
_CONNECT = "host=127.0.0.1 dbname=argos user=$0 sslmode=verify-full sslrootcert=/run/tls/ca.crt"
_DUMP = f'PGPASSWORD="$(cat)"; export PGPASSWORD; exec pg_dump -Fc "{_CONNECT}"'
_ROLES = (
    'PGPASSWORD="$(cat)"; export PGPASSWORD; '
    f'exec pg_dumpall --roles-only --no-role-passwords -d "{_CONNECT}"'
)


def dump_database(run: common.Runner, compose: Path, user: str, password: str, into: Path) -> None:
    """The dump and the roles, from inside the PostgreSQL container: the password goes on stdin."""
    into.mkdir(parents=True, exist_ok=True)
    base = ["docker", "compose", "-f", str(compose), "exec", "-T", "postgres", "sh", "-c"]
    (into / "argos.dump").write_bytes(run([*base, _DUMP, user], password.encode()))
    (into / "roles.sql").write_bytes(run([*base, _ROLES, user], password.encode()))


def configuration(run: common.Runner, vault: common.Vault, compose: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    (into / "vault-argos.json").write_text(
        json.dumps(vault.kv_tree(), ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    (into / "compose.yaml").write_bytes(compose.read_bytes())
    state = run(["docker", "compose", "-f", str(compose), "ps", "--all", "--format", "json"])
    (into / "compose-state.json").write_bytes(state)


def backup(
    restic: common.Restic,
    run: common.Runner,
    vault: common.Vault,
    compose: Path,
    evidence_volume: str,
    user: str,
    password: str,
    counts: Callable[[], dict[str, int]] | None = None,
) -> dict[str, str]:
    """The three sets; returns the snapshot of each.

    `counts` gives the rows of every table at the moment of the dump: the restore test compares
    the copy with them, not with production as it is later.
    """
    restic.ensure()
    snapshots: dict[str, str] = {}
    with workspace() as staging:
        dump_database(run, compose, user, password, staging / "db")
        if counts is not None:
            (staging / "db" / "counts.json").write_text(
                json.dumps(counts(), sort_keys=True), encoding="utf-8"
            )
        snapshots["db"] = restic.backup(["/staging/db"], "db", [(str(staging), "/staging", True)])
        snapshots["evidence"] = restic.backup(
            ["/evidence"], "evidence", [(evidence_volume, "/evidence", True)]
        )
        configuration(run, vault, compose, staging / "config")
        snapshots["config"] = restic.backup(
            ["/staging/config"], "config", [(str(staging), "/staging", True)]
        )
    restic.forget_and_check()
    return snapshots


def record(dsn: str, snapshots: dict[str, str], outcome: str, reason: str = "") -> None:
    detail: dict[str, Any] = {**snapshots, "reason": reason[:200]}
    if outcome == "succeeded":
        PostgresJournal(dsn).append(common.ACTOR, "backup.completed", detail)
    log = security_log.log(dsn)
    log.record("backup.completed", common.ACTOR, outcome, detail, source="argos-backup")
    log.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", default=os.environ.get("ARGOS_BACKUP_REPOSITORY"))
    parser.add_argument("--compose", type=Path, default=COMPOSE)
    parser.add_argument("--evidence-volume", default=EVIDENCE_VOLUME)
    parser.add_argument("--db-host", default=os.environ.get("ARGOS_BACKUP_DB_HOST", "127.0.0.1"))
    parser.add_argument(
        "--db-port", type=int, default=int(os.environ.get("ARGOS_BACKUP_DB_PORT", "55432"))
    )
    args = parser.parse_args(argv)
    if not args.repository:
        parser.error("--repository or ARGOS_BACKUP_REPOSITORY")
    vault = common.Vault(
        os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200"), os.environ.get("VAULT_TOKEN", "root")
    )
    user, password, lease = vault.database_credential()
    dsn = common.database_url(user, password, args.db_host, args.db_port)
    try:
        with common.Restic(common.docker, args.repository, vault.restic_password()) as restic:
            snapshots = backup(
                restic,
                common.docker,
                vault,
                args.compose,
                args.evidence_volume,
                user,
                password,
                PostgresProduction(dsn).counts,
            )
        record(dsn, snapshots, "succeeded")
    except Exception as failure:
        record(dsn, {}, "failed", str(failure))
        print(f"backup failed: {failure}", file=sys.stderr)
        return 1
    finally:
        vault.revoke(lease)
    print(json.dumps(snapshots, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
