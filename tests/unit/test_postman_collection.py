"""The Postman collection signs in with the accounts the environment names.

The bench has accounts for the team, for the front end team and for an external tester. The token
script takes the user of each role from `user_<role>` and falls back to the accounts of the team,
so one collection serves everybody and nobody edits its scripts.
"""

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
COLLECTION = ROOT / "tools" / "postman" / "ARGOS-API-v1.postman_collection.json"
BENCH = ROOT / "tools" / "postman" / "ARGOS-banco.postman_environment.json"
ROLES = ("manager", "dpo", "admin", "auditor")


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _script(owner: dict[str, Any], listen: str) -> str:
    return "\n".join(next(e for e in owner["event"] if e["listen"] == listen)["script"]["exec"])


def _token_script() -> str:
    return _script(_json(COLLECTION), "prerequest")


def test_the_token_script_takes_the_user_of_each_role_from_the_environment() -> None:
    script = _token_script()
    for role in ROLES:
        pattern = rf"pm\.variables\.get\('user_{role}'\)\s*\|\|\s*'{role}\.test'"
        assert re.search(pattern, script), role


def test_the_token_requests_of_folder_00_sign_in_with_the_same_account() -> None:
    folder = _json(COLLECTION)["item"][0]["item"]
    for role in ROLES:
        request = next(i for i in folder if i["name"] == f"Token · {role}.test")
        form = {f["key"]: f["value"] for f in request["request"]["body"]["urlencoded"]}
        assert form["username"] == "{{login_user}}", role
        before = _script(request, "prerequest")
        assert f"pm.variables.get('user_{role}') || '{role}.test'" in before, role
        after = _script(request, "test")
        assert f"'token_{role}_user'" in after, "the automatic token knows whose it is"


def test_the_bench_environment_has_a_user_for_each_role_and_no_value_in_it() -> None:
    values = {v["key"]: v for v in _json(BENCH)["values"]}
    for role in ROLES:
        assert values[f"user_{role}"]["value"] == "", "each person writes theirs as current value"
        assert values[f"password_{role}"]["value"] == ""
