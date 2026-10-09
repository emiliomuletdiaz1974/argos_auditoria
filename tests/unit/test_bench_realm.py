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

import yaml

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "bench_realm.py"
DEVELOPMENT = ROOT / "deploy" / "dev" / "keycloak" / "realm-argos.json"
BENCH = ROOT / "platform" / "k8s" / "base" / "core" / "keycloak" / "realm-bench.json"
API_DEPLOYMENT = ROOT / "platform" / "k8s" / "base" / "services" / "api.yaml"
# K-08A (DP-23): the front end of the bench is developed on the laptop of its team.
FRONT = "http://localhost:5173"


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


def test_the_bench_has_two_dpo_accounts_because_the_sampling_gate_asks_for_two_people() -> None:
    users = {u["username"]: u for u in _json(BENCH)["users"]}
    first, second = users["dpo.test"], users["dpo2.test"]
    assert second["realmRoles"] == first["realmRoles"] == ["dpo_reviewer", "default-roles-argos"]
    assert second["email"] != first["email"], "two people, not the same one twice"
    assert "dpo2.test" not in {u["username"] for u in _json(DEVELOPMENT)["users"]}, "bench only"


ROLES = {
    "manager": "campaign_manager",
    "dpo": "dpo_reviewer",
    "admin": "platform_admin",
    "auditor": "read_only_auditor",
}


def test_the_front_end_team_and_the_external_tester_have_one_account_per_role_each() -> None:
    """Each group signs in with its own accounts: a reset or a lockout of theirs never touches the
    accounts of the team, and the security log says who did what."""
    users = {u["username"]: u for u in _json(BENCH)["users"]}
    for group in ("front", "guest"):
        for short, role in ROLES.items():
            user = users[f"{group}.{short}"]
            assert user["realmRoles"] == [role, "default-roles-argos"], user["username"]
            assert user["email"] == f"{group}.{short}@argos.local"
    emails = [u["email"] for u in users.values()]
    assert len(emails) == len(set(emails)), "one address per account"
    development = {u["username"] for u in _json(DEVELOPMENT)["users"]}
    assert not {u for u in users if u.startswith(("front.", "guest."))} & development, "bench only"


def _client(realm: dict[str, Any], client_id: str) -> dict[str, Any]:
    return next(c for c in realm["clients"] if c["clientId"] == client_id)


def test_the_console_client_takes_back_only_the_front_end_of_the_bench() -> None:
    """Not the addresses of development (127.0.0.1): a bench open to the internet lists the one
    front end it was told about, and Keycloak refuses any other return address."""
    console = _client(_json(BENCH), "argos-console")
    assert console["redirectUris"] == [f"{FRONT}/*"]
    assert console["webOrigins"] == [FRONT]


def test_the_api_of_the_bench_answers_the_same_origin_the_realm_takes_back() -> None:
    """The realm and the API must name the same front end, or the sign-in works and the first
    call from the page is refused by CORS (or the other way round)."""
    documents = yaml.safe_load_all(API_DEPLOYMENT.read_text(encoding="utf-8"))
    deployment = next(d for d in documents if d)
    env = {
        e["name"]: e.get("value")
        for e in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert env["ARGOS_FRONTEND_ORIGINS"] == FRONT
    assert _client(_json(BENCH), "argos-console")["webOrigins"] == [env["ARGOS_FRONTEND_ORIGINS"]]


def test_every_account_of_the_bench_has_the_default_roles() -> None:
    """Without default-roles-argos the account page of Keycloak answers 401."""
    for user in _json(BENCH)["users"]:
        assert "default-roles-argos" in user["realmRoles"], user["username"]
