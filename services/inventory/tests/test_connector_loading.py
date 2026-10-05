"""K-07 · several scans that start at once load their connectors safely.

The scheduler of the bench launched four scans in a fresh process, each in its own thread, and the
SQL ones failed: importing `argos_sql.postgres` and `argos_sql.generic` at the same moment ends in a
deadlock that importlib breaks with `_DeadlockError`, a RuntimeError that escaped as KeyError or
"connector not found". In development the scans never started together in a fresh process. A fresh
interpreter is the only place to see it, so the check runs in one, several times.
"""

import subprocess
import sys

PROGRAM = """
import concurrent.futures as cf, threading
from argos_inventory.discovery.probes import connector_class
paths = ["argos_sql.postgres:PostgresConnector", "argos_sql.generic:SqlConnector",
         "argos_files.connector:FilesConnector", "argos_ldap.connector:LdapConnector"]
start = threading.Barrier(len(paths))
def load(path):
    start.wait()
    try:
        connector_class(path)
        return "ok"
    except Exception as exc:
        return type(exc).__name__
with cf.ThreadPoolExecutor(len(paths)) as pool:
    print(",".join(pool.map(load, paths)))
"""


def test_connectors_loaded_at_once_from_several_threads_all_load() -> None:
    for _ in range(5):
        answer = subprocess.run(  # noqa: S603 - this interpreter, a fixed program
            [sys.executable, "-c", PROGRAM], capture_output=True, text=True, check=True, timeout=120
        )
        assert answer.stdout.strip() == "ok,ok,ok,ok", answer.stdout
