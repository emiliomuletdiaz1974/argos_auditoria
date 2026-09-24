"""F09-15 · the access battery: attacking the deployed API as someone inside the network would.

The matrix role × permission is checked in the contract (F08-02); here it is checked against the
running `api` container, with real tokens of the realm, and the state is looked at afterwards:
a refusal that left an effect is not a refusal. Then the tokens nobody should be able to use,
the separation of duties, the surface of the console and the internal services, and whether
every attempt reached the security log.

Each check is recorded; `tools/security_report.py` turns the results into
`docs/seguridad/bateria-accesos.md` for the dossier. The battery uses its own campaign and its own
users: it does not depend on the order of the tests nor on what another test left.
"""

import base64
import datetime as dt
import json
import os
import socket
import ssl
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import jwt
import psycopg
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa

from argos_challenges.store import pin_campaign, request_approval

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
API = os.environ.get("ARGOS_TEST_API", "http://127.0.0.1:8000")
KEYCLOAK = os.environ.get("ARGOS_TEST_KEYCLOAK", "http://127.0.0.1:8180")
# The API validates the issuer it sees inside the compose network. Keycloak builds the issuer
# from the Host header, so the tokens are asked for as the containers ask for them.
INTERNAL_HOST = "keycloak:8080"
ISSUER = f"http://{INTERNAL_HOST}/realms/argos"
ADMIN_DSN = os.environ.get("ARGOS_TEST_DSN", "postgresql://argos@127.0.0.1:55432/argos")
RESULTS = Path(
    os.environ.get("ARGOS_BATTERY_RESULTS", REPO / "dist" / "security" / "access-battery.json")
)
USERS = {
    "platform_admin": "admin.test",
    "campaign_manager": "manager.test",
    "dpo_reviewer": "dpo.test",
    "read_only_auditor": "auditor.test",
}
MATRIX = yaml.safe_load((REPO / "tests" / "fixtures" / "authz_matrix.yaml").read_text("utf-8"))
_results: list[dict[str, Any]] = []


def _load_keycloak() -> Any:
    """The helpers of the integration tests (TOTP codes of the development realm, its admin)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "battery_keycloak", REPO / "tests" / "integration" / "keycloak.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


keycloak = _load_keycloak()


def record(category: str, case: str, expected: str, got: str, ok: bool) -> None:
    _results.append(
        {"category": category, "case": case, "expected": expected, "got": got, "ok": ok}
    )


@pytest.fixture(scope="module", autouse=True)
def _write_results() -> Any:
    started = dt.datetime.now(dt.UTC)
    yield
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(
        json.dumps(
            {"started": started.isoformat(), "api": API, "results": _results},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


# ------------------------------------------------------------------ tokens of the realm


def _token_answer(
    username: str, client: str = "argos-tests", realm: str = "argos"
) -> dict[str, Any]:
    form = {"grant_type": "password", "client_id": client, "username": username, "scope": "openid"}
    form["password"] = "admin" if realm == "master" else "test"
    if realm == "master":
        form["client_id"] = "admin-cli"
    for _ in range(3):
        if realm == "argos" and keycloak.totp_secret(username) is not None:
            form["totp"] = keycloak.next_code(username)
        answer = httpx.post(
            f"{KEYCLOAK}/realms/{realm}/protocol/openid-connect/token",
            data=form,
            headers={"Host": INTERNAL_HOST},
            timeout=10,
        )
        if answer.status_code == 200:
            return dict(answer.json())
        keycloak.spent(username)  # a code another run of this window already used
        time.sleep(1)
    raise AssertionError(f"no token for {username}: {answer.text}")


_cache: dict[str, str] = {}


def _token(role: str) -> str:
    if role not in _cache:
        _cache[role] = str(_token_answer(USERS[role])["access_token"])
    return _cache[role]


def _sub(role: str) -> str:
    part = _token(role).split(".")[1]
    return str(json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))["sub"])


def _call(method: str, path: str, token: str | None, **kwargs: Any) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}))
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.request(method, API + path, headers=headers, timeout=20, **kwargs)


def _journal_head() -> int:
    with psycopg.connect(ADMIN_DSN) as conn:
        row = conn.execute("SELECT coalesce(max(seq), 0) FROM argos.audit_journal").fetchone()
    return int(row[0]) if row else 0


def _journal_by(actors: list[str], after: int) -> int:
    with psycopg.connect(ADMIN_DSN) as conn:
        row = conn.execute(
            "SELECT count(*) FROM argos.audit_journal WHERE seq > %s AND actor = ANY(%s)",
            (after, actors),
        ).fetchone()
    return int(row[0]) if row else 0


def _routes() -> list[tuple[str, str, str]]:
    from fastapi.routing import APIRoute

    from argos_api import API_PREFIX
    from argos_api.app import AUTHENTICATED
    from argos_api.authz import PermissionGuard

    found = []
    for router in AUTHENTICATED:
        for route in router.routes:
            assert isinstance(route, APIRoute)
            guards = [
                d.dependency.permission
                for d in route.dependencies
                if isinstance(d.dependency, PermissionGuard)
            ]
            for method in sorted(route.methods - {"HEAD"}):
                found.append((method, API_PREFIX + route.path, guards[0]))
    return found


def _concrete(path: str) -> str:
    ids = {
        "{campaign_id}": str(uuid.uuid4()),
        "{finding_id}": str(uuid.uuid4()),
        "{node_key}": "k-node-battery",
        "{credential_id}": f"urn:uuid:{uuid.uuid4()}",
        "{verdict_id}": str(uuid.uuid4()),
        "{webhook_id}": str(uuid.uuid4()),
        "{gate}": "sampling",
        "{diagnostics_id}": "1790000000-0a1b2c3d",
        "{injection_id}": str(uuid.uuid4()),
        "{number}": "0",
    }
    for placeholder, value in ids.items():
        path = path.replace(placeholder, value)
    return path


# ------------------------------------------------------------------ the matrix


@pytest.mark.parametrize("role", sorted(USERS))
def test_every_refused_combination_is_refused_by_the_deployed_api_and_leaves_no_trace(
    role: str,
) -> None:
    token = _token(role)
    before = _journal_head()
    refused = 0
    for method, path, permission in _routes():
        if MATRIX[role][permission]:
            continue  # what the role may do is not attacked here: it would change the state
        answer = _call(method, _concrete(path), token, json={})
        ok = answer.status_code == 403
        record("matrix", f"{role} {method} {path}", "403", str(answer.status_code), ok)
        assert ok, (role, method, path, answer.status_code, answer.text[:200])
        refused += 1
    assert refused > 0
    left = _journal_by([f"user:{_sub(role)}"], before)
    record(
        "matrix", f"{role}: journal entries left by {refused} refusals", "0", str(left), left == 0
    )
    assert left == 0, "a refused request left an entry in the journal"


def test_the_roles_that_decide_get_no_token_without_their_code() -> None:
    for role in ("platform_admin", "dpo_reviewer"):
        answer = httpx.post(
            f"{KEYCLOAK}/realms/argos/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "argos-tests",
                "scope": "openid",
                "username": USERS[role],
                "password": "test",
            },  # fmt: skip
            headers={"Host": INTERNAL_HOST},
            timeout=10,
        )
        ok = answer.status_code == 401
        record(
            "second factor",
            f"{role} signs in without the TOTP code",
            "401",
            str(answer.status_code),
            ok,
        )
        assert ok
    for user in (USERS["platform_admin"], USERS["dpo_reviewer"]):
        [found] = keycloak.admin("GET", f"/users?username={user}&exact=true")
        keycloak.admin("DELETE", f"/attack-detection/brute-force/users/{found['id']}")


# ------------------------------------------------------------------ tokens nobody may use


def _claims(token: str) -> dict[str, Any]:
    part = token.split(".")[1]
    return dict(json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))))


def _forged(claims: dict[str, Any], algorithm: str = "RS256") -> str:
    if algorithm == "none":
        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        return f"{header}.{body}."
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = jwt.get_unverified_header(_token("dpo_reviewer"))["kid"]
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


def _refused(case: str, token: str, expected: int = 401) -> None:
    answer = _call("GET", "/api/v1/campaigns", token)
    ok = answer.status_code == expected
    record("tokens", case, str(expected), str(answer.status_code), ok)
    assert ok, (case, answer.status_code, answer.text[:200])


def test_a_token_signed_with_another_key_is_refused() -> None:
    _refused("signed with another key (same kid)", _forged(_claims(_token("dpo_reviewer"))))


def test_a_token_with_alg_none_is_refused() -> None:
    _refused("alg none", _forged(_claims(_token("dpo_reviewer")), "none"))


def test_a_token_whose_payload_was_changed_is_refused() -> None:
    real = _token("read_only_auditor")
    header, _, signature = real.split(".")
    claims = _claims(real)
    claims["realm_access"] = {"roles": ["platform_admin", "dpo_reviewer"]}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    _refused("real signature over a changed payload (roles added)", f"{header}.{body}.{signature}")


def test_an_expired_token_is_refused() -> None:
    answer = _token_answer("manager.test", client="argos-expiring")
    time.sleep(int(answer.get("expires_in", 5)) + 2)
    _refused("expired (client argos-expiring, 5 s)", str(answer["access_token"]))


def test_a_token_for_another_audience_is_refused() -> None:
    answer = _token_answer("manager.test", client="argos-other")
    assert "argos-api" not in (_claims(answer["access_token"]).get("aud") or [])
    _refused("audience of another client (argos-other)", str(answer["access_token"]))


def test_a_token_of_another_realm_is_refused() -> None:
    answer = _token_answer("admin", realm="master")
    _refused("issuer of another realm (master, admin-cli)", str(answer["access_token"]))


def test_an_account_without_roles_gets_nothing() -> None:
    # The workers have no identity in Keycloak (they use their database role and mTLS): the
    # closest thing, an account of the realm with no role of ARGOS, is refused on every route.
    token = str(_token_answer("lockout.test")["access_token"])
    for method, path, _ in _routes()[:25]:
        answer = _call(method, _concrete(path), token, json={})
        ok = answer.status_code == 403
        record(
            "tokens", f"account without roles {method} {path}", "403", str(answer.status_code), ok
        )
        assert ok


def test_no_token_at_all_is_refused() -> None:
    answer = _call("GET", "/api/v1/campaigns", None)
    ok = answer.status_code == 401 and "Bearer" in answer.headers.get("www-authenticate", "")
    record("tokens", "no token", "401 with WWW-Authenticate", str(answer.status_code), ok)
    assert ok


@pytest.mark.xfail(
    strict=True,
    reason="SEC-060: an access token lives until it expires (5 min at most) after logout; F09-32",
)
def test_a_token_is_refused_after_its_session_was_closed() -> None:
    answer = _token_answer("manager.test")
    access, refresh = str(answer["access_token"]), str(answer["refresh_token"])
    closed = httpx.post(f"{API}/api/v1/auth/logout", cookies={"argos_refresh": refresh}, timeout=10)
    assert closed.status_code in (200, 204)
    got = _call("GET", "/api/v1/campaigns", access).status_code
    record("tokens", "access token after logout", "401", str(got), got == 401)
    assert got == 401


# ------------------------------------------------------------------ separation of duties


@pytest.fixture(scope="module")
def sampling_campaign() -> str:
    created = _call(
        "POST",
        "/api/v1/campaigns",
        _token("campaign_manager"),
        json={"name": f"Batería de accesos {dt.date.today()}"},
    )
    assert created.status_code == 201, created.text
    campaign = str(created.json()["campaign_id"])
    pin_campaign(
        ADMIN_DSN, campaign, snapshot_id=None, snapshot_hash=None, ontology_version="1.0.0",
        library_version="1.0.0", library_sha256="b" * 64, applicability_run=None,
    )  # fmt: skip
    request_approval(ADMIN_DSN, campaign, "sampling", {"units": 1})
    return campaign


def test_whoever_runs_the_campaign_cannot_approve_its_gate(sampling_campaign: str) -> None:
    path = f"/api/v1/campaigns/{sampling_campaign}/gates/sampling/approve"
    got = _call("POST", path, _token("campaign_manager"), json={}).status_code
    record(
        "separation of duties",
        "the campaign manager approves the sampling gate",
        "403",
        str(got),
        got == 403,
    )
    assert got == 403


def test_the_same_person_does_not_count_twice_in_the_double_control(sampling_campaign: str) -> None:
    path = f"/api/v1/campaigns/{sampling_campaign}/gates/sampling/approve"
    first = _call("POST", path, _token("dpo_reviewer"), json={})
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "awaiting_second_approval"
    again = _call("POST", path, _token("dpo_reviewer"), json={})
    ok = again.status_code == 409
    record(
        "separation of duties",
        "the same DPO approves the sampling gate twice",
        "409",
        str(again.status_code),
        ok,
    )
    assert ok
    gates = _call("GET", f"/api/v1/campaigns/{sampling_campaign}/gates", _token("dpo_reviewer"))
    sampling = next(g for g in gates.json()["items"] if g["gate"] == "sampling")
    assert sampling["approvals"] == 1, "the second approval of the same person did not count"


@pytest.fixture(scope="module")
def own_finding() -> dict[str, Any]:
    """A finding of the battery itself: a non-compliant verdict of its own campaign."""
    from argos_challenges.evaluator import evaluate
    from argos_challenges.findings import open_or_recur
    from argos_challenges.store import create_campaign, persist_verdict, save_units
    from argos_common.journal_pg import PostgresJournal

    with psycopg.connect(ADMIN_DSN) as conn:
        row = conn.execute("SELECT id::text FROM argos.systems ORDER BY id LIMIT 1").fetchone()
    assert row is not None, "the development environment registers its systems in make dev"
    campaign = create_campaign(
        ADMIN_DSN, "Batería de accesos · hallazgo", {}, f"user:{_sub('campaign_manager')}"
    )
    pin_campaign(
        ADMIN_DSN, campaign, snapshot_id=None, snapshot_hash=None, ontology_version="1.0.0",
        library_version="1.0.0", library_sha256="b" * 64, applicability_run=None,
    )  # fmt: skip
    node = f"k-battery-{uuid.uuid4().hex[:8]}"
    unit = {
        "unit_id": node.ljust(64, "0")[:64], "campaign_id": campaign,
        "challenge_id": "sec-encryption-in-transit", "challenge_version": "1.0",
        "obligation": "OBL-RGPD-32-1", "system_id": row[0], "node_key": node,
        "probe": {"kind": "sql", "target": "public.patients", "statement": "SHOW ssl",
                  "params": {}},
        "criterion": {"threshold": {"field": "rows.0.ssl", "operator": "==", "value": "on"}},
        "sampling": None, "severity": "high",
    }  # fmt: skip
    save_units(ADMIN_DSN, campaign, [unit])
    probe = {"ok": True, "data": {"rows": [{"ssl": "off"}]}}
    seq = PostgresJournal(ADMIN_DSN).append(
        "system:probe", "probe.issued", {"unit": unit["unit_id"]}
    )
    verdict = evaluate(unit, probe)
    verdict_id, _ = persist_verdict(ADMIN_DSN, campaign, unit, verdict, probe_journal_seq=seq)
    return dict(open_or_recur(ADMIN_DSN, campaign, unit, verdict, verdict_id))


def test_nobody_closes_a_finding_by_hand(own_finding: dict[str, Any]) -> None:
    finding = str(own_finding["id"])
    before = _call("GET", f"/api/v1/findings/{finding}", _token("dpo_reviewer")).json()["status"]
    for target in ("closed_compliant", "reopened"):
        answer = _call(
            "POST", f"/api/v1/findings/{finding}/transition", _token("dpo_reviewer"),
            json={"to": target, "note": "cierre a mano"},
        )  # fmt: skip
        ok = answer.status_code in (409, 422)
        record(
            "separation of duties", f"the DPO moves a finding to {target} by hand",
            "409/422", str(answer.status_code), ok,
        )  # fmt: skip
        assert ok, answer.text
    after = _call("GET", f"/api/v1/findings/{finding}", _token("dpo_reviewer")).json()["status"]
    assert after == before


# ------------------------------------------------------------------ surface


def test_an_undeclared_route_is_a_plain_problem_without_a_stack() -> None:
    answer = _call("GET", "/api/v1/nothing-here", _token("read_only_auditor"))
    body = answer.text
    ok = (
        answer.status_code == 404
        and answer.headers["content-type"].startswith("application/problem+json")
        and "Traceback" not in body and "File \"" not in body
    )  # fmt: skip
    record(
        "surface",
        "undeclared route",
        "404 problem+json without a stack",
        str(answer.status_code),
        ok,
    )
    assert ok


def test_the_console_carries_its_security_headers() -> None:
    answer = httpx.get(f"{API}/", timeout=10)
    csp = answer.headers.get("content-security-policy", "")
    checks = {
        "CSP without unsafe-inline": "unsafe-inline" not in csp and "default-src 'self'" in csp,
        "frame-ancestors 'none'": "frame-ancestors 'none'" in csp,
        "X-Content-Type-Options nosniff": answer.headers.get("x-content-type-options") == "nosniff",
        "Referrer-Policy": bool(answer.headers.get("referrer-policy")),
    }
    for name, ok in checks.items():
        record("surface", f"console header: {name}", "present", "present" if ok else "missing", ok)
    assert all(checks.values()), checks


def test_the_refresh_cookie_does_not_travel_outside_its_path() -> None:
    from argos_api.routers.session import COOKIE_PATH

    ok = COOKIE_PATH == "/api/v1/auth"
    source = (REPO / "services" / "api" / "argos_api" / "routers" / "session.py").read_text("utf-8")
    ok = (
        ok
        and "httponly=True" in source
        and 'samesite="strict"' in source
        and "secure=True" in source
    )
    record(
        "surface",
        "refresh cookie: path /api/v1/auth, HttpOnly, Secure, SameSite=Strict",
        "yes",
        "yes" if ok else "no",
        ok,
    )
    assert ok


def test_a_mutation_from_a_foreign_origin_is_refused() -> None:
    before = _journal_head()
    answer = _call(
        "POST",
        "/api/v1/campaigns",
        _token("campaign_manager"),
        json={"name": "desde otro origen"},
        headers={"Origin": "https://attacker.example"},
    )
    ok = (
        answer.status_code == 403 and _journal_by([f"user:{_sub('campaign_manager')}"], before) == 0
    )
    record(
        "surface",
        "POST with Origin https://attacker.example",
        "403, nothing created",
        str(answer.status_code),
        ok,
    )
    assert ok, answer.text


def test_a_mutation_from_its_own_origin_goes_through() -> None:
    answer = _call(
        "POST",
        "/api/v1/campaigns",
        _token("campaign_manager"),
        json={"name": f"Batería · mismo origen {uuid.uuid4().hex[:6]}"},
        headers={"Origin": API},
    )
    ok = answer.status_code == 201
    record("surface", "POST with the Origin of the console", "201", str(answer.status_code), ok)
    assert ok, answer.text


# ------------------------------------------------------------------ internal services


def _handshake(host: str, port: int) -> str:
    """A TLS client without a certificate, as a container without one would be."""
    ca = REPO / "deploy" / "dev" / "secrets" / "tls-host" / "ca.crt"
    context = ssl.create_default_context(cafile=str(ca))
    context.check_hostname = False
    try:
        with (
            socket.create_connection((host, port), timeout=5) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            tls.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            data = tls.recv(64)
            return "answered" if data else "closed"
    except (ssl.SSLError, ConnectionError, OSError) as refused:
        return f"refused ({type(refused).__name__})"


@pytest.mark.parametrize(("service", "port"), [("ai-gateway", 8005), ("nats", 4222)])
def test_an_internal_service_does_not_answer_a_client_without_certificate(
    service: str, port: int
) -> None:
    got = _handshake("127.0.0.1", port)
    ok = got.startswith("refused") or got == "closed"
    record("internal services", f"{service} without a client certificate", "refused", got, ok)
    assert ok, got


def test_the_database_refuses_a_connection_without_tls() -> None:
    try:
        psycopg.connect(ADMIN_DSN.split("?")[0] + "?sslmode=disable", connect_timeout=5).close()
        got = "accepted"
    except psycopg.OperationalError:
        got = "refused"
    record("internal services", "PostgreSQL without TLS", "refused", got, got == "refused")
    assert got == "refused"


@pytest.mark.parametrize(
    ("service", "base", "path"),
    [
        ("public verifier", "http://127.0.0.1:8007", "/docs"),
        ("public verifier", "http://127.0.0.1:8007", "/openapi.json"),
        ("evidence-api", "http://127.0.0.1:8008", "/docs"),
        ("evidence-api", "http://127.0.0.1:8008", "/openapi.json"),
        ("evidence-api", "http://127.0.0.1:8008", "/admin"),
    ],
)
def test_the_public_services_expose_nothing_but_what_is_public(
    service: str, base: str, path: str
) -> None:
    got = httpx.get(base + path, timeout=10).status_code
    ok = got in (401, 403, 404, 405)
    record("public services", f"{service} {path}", "404", str(got), ok)
    assert ok


# ------------------------------------------------------------------ the security log


def test_every_kind_of_attempt_reached_the_security_log() -> None:
    time.sleep(1)
    with psycopg.connect(ADMIN_DSN) as conn:
        kinds = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT kind FROM security.events WHERE at > now() - interval '30 minutes'"
                " AND outcome = 'refused'"
            ).fetchall()
        }
    for kind in ("auth.token_rejected", "authz.denied"):
        ok = kind in kinds
        record(
            "security log",
            f"refused attempts of kind {kind}",
            "recorded",
            "recorded" if ok else "missing",
            ok,
        )
        assert ok, kinds
