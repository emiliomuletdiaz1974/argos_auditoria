"""K-05 · the realm of the bench is the one of development, without anything that is public.

The development realm keeps in the public repository the passwords of its users and the TOTP
secrets of the people who decide. The bench realm is generated from it by tools/bench_realm.py:
the same roles, flows and second factor, the clients ARGOS uses, and its users without a single
credential. They set their password, and the people who decide their TOTP, the first time they
sign in. The generated file is versioned, and a test keeps it in step with its source.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "bench_realm.py"
DEVELOPMENT = ROOT / "deploy" / "dev" / "keycloak" / "realm-argos.json"
BENCH = ROOT / "platform" / "k8s" / "base" / "core" / "keycloak" / "realm-bench.json"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_realm", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_the_versioned_bench_realm_is_the_generated_one() -> None:
    assert _json(BENCH) == _tool().bench_realm(_json(DEVELOPMENT))


def test_no_user_of_the_bench_carries_a_credential() -> None:
    realm = _json(BENCH)
    text = BENCH.read_text(encoding="utf-8")
    assert "dev-only" not in text and '"secretData"' not in text and '"credentials"' not in text
    for user in realm["users"]:
        assert "credentials" not in user, user["username"]


def test_every_user_sets_a_password_and_the_people_who_decide_their_second_factor() -> None:
    for user in _json(BENCH)["users"]:
        actions = set(user["requiredActions"])
        assert "UPDATE_PASSWORD" in actions, user["username"]
        decides = {"platform_admin", "dpo_reviewer"} & set(user.get("realmRoles", []))
        assert ("CONFIGURE_TOTP" in actions) == bool(decides), user["username"]


def test_the_bench_keeps_the_roles_flows_and_policies_of_development() -> None:
    development, bench = _json(DEVELOPMENT), _json(BENCH)
    for key in ("roles", "authenticationFlows", "authenticatorConfig", "browserFlow"):
        assert bench[key] == development[key], key
    for key in ("otpPolicyAlgorithm", "passwordPolicy", "bruteForceProtected", "failureFactor"):
        assert bench[key] == development[key], key


def test_only_the_clients_argos_uses_and_none_made_for_tests() -> None:
    clients = {c["clientId"] for c in _json(BENCH)["clients"]}
    assert clients == {"argos-console", "argos-api", "argos-tests"}
    users = {u["username"] for u in _json(BENCH)["users"]}
    assert "lockout.test" not in users, "the account of the lockout test stays in development"
