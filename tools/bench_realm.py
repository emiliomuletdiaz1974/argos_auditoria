"""K-05 · the realm of the bench, generated from the realm of development without what is public.

  uv run python tools/bench_realm.py          writes the realm of the bench (realm-bench.json)
  uv run python tools/bench_realm.py --check  fails if the versioned file is not the generated one

It keeps the roles, the flows, the second factor and the policies of development, and the clients
ARGOS uses (`argos-tests` serves the Postman collection and the access battery on synthetic data).
The console client returns only to the front end of the bench (`FRONT_ORIGIN`), not to the
addresses of development.
It drops the clients made only for tests and the account of the lockout test, and every credential:
the users set their password, and the people who decide their TOTP, the first time they sign in.
"""

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT = ROOT / "deploy" / "dev" / "keycloak" / "realm-argos.json"
BENCH = ROOT / "platform" / "k8s" / "base" / "core" / "keycloak" / "realm-bench.json"
CLIENTS = ("argos-console", "argos-api", "argos-tests")
TEST_ONLY_USERS = ("lockout.test",)
DECIDE = {"platform_admin", "dpo_reviewer"}
# K-08A (DP-23): the front end is developed on the laptop of its team. The bench takes back this
# origin and no other; the same value is ARGOS_FRONTEND_ORIGINS in the API deployment (api.yaml).
FRONT_ORIGIN = "http://localhost:5173"


def bench_realm(development: dict[str, Any]) -> dict[str, Any]:
    realm = copy.deepcopy(development)
    realm["clients"] = [c for c in realm["clients"] if c["clientId"] in CLIENTS]
    for client in realm["clients"]:
        if client["clientId"] == "argos-console":
            client["redirectUris"] = [f"{FRONT_ORIGIN}/*"]
            client["webOrigins"] = [FRONT_ORIGIN]
    users = []
    for user in realm["users"]:
        if user["username"] in TEST_ONLY_USERS:
            continue
        user.pop("credentials", None)
        actions = ["UPDATE_PASSWORD"]
        if DECIDE & set(user.get("realmRoles", [])):
            actions.append("CONFIGURE_TOTP")
        user["requiredActions"] = actions
        users.append(user)
    realm["users"] = users
    return realm


def _render(development: dict[str, Any]) -> str:
    return json.dumps(bench_realm(development), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    rendered = _render(json.loads(DEVELOPMENT.read_text(encoding="utf-8")))
    if args.check:
        if not BENCH.is_file() or BENCH.read_text(encoding="utf-8") != rendered:
            print(f"{BENCH.relative_to(ROOT)} is stale: run tools/bench_realm.py", file=sys.stderr)
            return 1
        return 0
    BENCH.parent.mkdir(parents=True, exist_ok=True)
    BENCH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"written {BENCH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
