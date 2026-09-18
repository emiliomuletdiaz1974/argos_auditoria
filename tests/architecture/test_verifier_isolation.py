"""ARG-069 · the public verifier needs no database, no store and no platform service.

A third party runs it with what it is given, so importing it must not pull in
anything that talks to PostgreSQL, the WORM store, NATS, Temporal or Vault.
The check runs in a fresh interpreter, so it sees every transitive import.
"""

import json
import subprocess
import sys

FORBIDDEN = (
    "psycopg",
    "boto3",
    "botocore",
    "hvac",
    "nats",
    "temporalio",
    "argos_evidence.worm",
    "argos_evidence.artifacts",
    "argos_evidence.signing",
    "argos_evidence.tsa",
    "argos_evidence.journal",
    "argos_evidence.dossier",
    "argos_evidence.credential.issue",
    "argos_challenges",
    "argos_inventory",
)
PROBE = (
    "import json, sys; import argos_verifier.checks, argos_verifier.api; "
    "print(json.dumps(sorted(sys.modules)))"
)


def test_importing_the_verifier_loads_nothing_that_touches_the_platform() -> None:
    done = subprocess.run(  # noqa: S603 - fixed interpreter and a fixed probe
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    )
    loaded = json.loads(done.stdout)
    offenders = [m for m in loaded if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)]
    assert offenders == []
