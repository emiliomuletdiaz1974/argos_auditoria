"""Parameters the client declares and approves (ARG-042, ARG-036).

The retention calendar, the authorised profiles and the campaign parameters are the client's, not
ARGOS'. They live beside the Rego data because OPA reads the same file, and the compiler resolves
`{"$client": …}` references from here: what a challenge measures against is what the client
approved.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from argos_ontology.vocabulary import LIBRARY_DIR

CLIENT_DATA_FILE = LIBRARY_DIR.parent / "deploy" / "dev" / "opa" / "client" / "data.json"


@lru_cache(maxsize=4)
def client_data(path: Path = CLIENT_DATA_FILE) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def client_parameters(path: Path = CLIENT_DATA_FILE) -> dict[str, Any]:
    """The flat parameters a challenge may reference with `{"$client": …}`."""
    return dict(client_data(path).get("campaign_parameters", {}))
