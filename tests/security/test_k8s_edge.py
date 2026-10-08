"""K-08 · the public entry of the bench, checked before it reaches the cluster.

Two names, no domain of our own (K-08A, DP-23): the API at api.34-134-21-66.sslip.io and the sign-in
of Keycloak at id.34-134-21-66.sslip.io, each with a certificate of Let's Encrypt and only on 443.
From Keycloak only what a browser needs (`/realms/argos`, `/resources`): its administration and the
master realm stay inside.
The third name, ns.34-134-21-66.sslip.io, stands for ns.argos.eu until that domain is ours: it
serves `/norms/`, so the IRIs of the obligations open, and `/verify`, where the QR of a dossier
points (public verifier).
Nothing else of the cluster has a way in: no other Ingress, no LoadBalancer, no NodePort.
"""

from pathlib import Path
from typing import Any

import yaml

K8S = Path(__file__).resolve().parents[2] / "platform" / "k8s"
API_HOST = "api.34-134-21-66.sslip.io"
ID_HOST = "id.34-134-21-66.sslip.io"
NORMS_HOST = "ns.34-134-21-66.sslip.io"
ISSUER = f"https://{ID_HOST}/realms/argos"
TRAEFIK = {
    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
    "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}},
}


def _documents() -> list[dict[str, Any]]:
    documents = []
    for path in sorted((K8S / "base").rglob("*.yaml")):
        documents += [d for d in yaml.safe_load_all(path.read_text("utf-8")) if isinstance(d, dict)]
    return documents


def _named(kind: str, name: str, namespace: str) -> dict[str, Any]:
    [found] = [
        d
        for d in _documents()
        if d.get("kind") == kind
        and d["metadata"]["name"] == name
        and d["metadata"].get("namespace") == namespace
    ]
    return found


def _env(kind: str, name: str, namespace: str) -> dict[str, Any]:
    pod = _named(kind, name, namespace)["spec"]["template"]["spec"]
    [container] = [c for c in pod["containers"] if c["name"] == name]
    return {e["name"]: e.get("value") for e in container.get("env", [])}


def test_lets_encrypt_signs_the_names_by_http01_through_traefik() -> None:
    [issuer] = [d for d in _documents() if d.get("kind") == "ClusterIssuer" and "acme" in d["spec"]]
    assert issuer["metadata"]["name"] == "letsencrypt"
    acme = issuer["spec"]["acme"]
    assert acme["server"] == "https://acme-v02.api.letsencrypt.org/directory"
    assert acme["solvers"] == [{"http01": {"ingress": {"ingressClassName": "traefik"}}}]


def test_only_the_api_the_sign_in_and_the_norms_have_a_way_in() -> None:
    ingresses = {
        (d["metadata"]["namespace"], d["metadata"]["name"])
        for d in _documents()
        if d.get("kind") == "Ingress"
    }
    assert ingresses == {
        ("argos-services", "api"),
        ("argos-core", "keycloak"),
        ("argos-services", "norms"),
    }
    for document in _documents():
        if document.get("kind") == "Service":
            assert document["spec"].get("type", "ClusterIP") == "ClusterIP", document["metadata"]


def _check_ingress(ingress: dict[str, Any], host: str, service: str, port: int) -> list[str]:
    annotations = ingress["metadata"]["annotations"]
    assert annotations["cert-manager.io/cluster-issuer"] == "letsencrypt"
    assert annotations["traefik.ingress.kubernetes.io/router.entrypoints"] == "websecure"
    spec = ingress["spec"]
    assert spec["ingressClassName"] == "traefik"
    [tls] = spec["tls"]
    assert tls["hosts"] == [host]
    [rule] = spec["rules"]
    assert rule["host"] == host
    paths = []
    for path in rule["http"]["paths"]:
        assert path["pathType"] == "Prefix"
        assert path["backend"]["service"] == {"name": service, "port": {"number": port}}
        paths.append(path["path"])
    return paths


def test_the_api_is_published_whole_on_its_name() -> None:
    paths = _check_ingress(_named("Ingress", "api", "argos-services"), API_HOST, "api", 8000)
    assert paths == ["/"]


def test_from_keycloak_only_what_a_browser_signs_in_with() -> None:
    paths = _check_ingress(_named("Ingress", "keycloak", "argos-core"), ID_HOST, "keycloak", 8080)
    # Only the realm of ARGOS: the master realm signs in the administrator of Keycloak, and
    # publishing it opens that sign-in to the internet (found by the curl tests of the bench).
    assert sorted(paths) == ["/realms/argos", "/resources"], "nor the administration nor master"


def test_from_the_verifier_the_norms_namespace_and_the_check() -> None:
    """The IRIs of the obligations open, and so does the QR of a dossier; nothing else of it."""
    ingress = _named("Ingress", "norms", "argos-services")
    paths = _check_ingress(ingress, NORMS_HOST, "verifier", 8007)
    assert sorted(paths) == ["/norms/", "/verify"]


def test_the_dossiers_point_their_qr_to_the_public_verifier_of_the_bench() -> None:
    """An address inside the cluster in a printed QR opens nowhere (seen on 2026-10-08)."""
    for kind, name in (
        ("Deployment", "evidence-worker"),
        ("Deployment", "evidence-api"),
        ("Deployment", "api"),
    ):
        env = _env(kind, name, "argos-services")
        assert env["ARGOS_EVIDENCE_VERIFIER_URL"] == f"https://{NORMS_HOST}/verify", name


def test_keycloak_names_itself_by_the_public_name_and_answers_inside_too() -> None:
    env = _env("Deployment", "keycloak", "argos-core")
    assert env["KC_HOSTNAME"] == f"https://{ID_HOST}"
    assert env["KC_HOSTNAME_BACKCHANNEL_DYNAMIC"] == "true"
    assert env["KC_PROXY_HEADERS"] == "xforwarded"
    pod = _named("Deployment", "keycloak", "argos-core")["spec"]["template"]["spec"]
    [container] = [c for c in pod["containers"] if c["name"] == "keycloak"]
    assert "--hostname-strict=false" not in container["args"]


def test_the_api_checks_the_public_issuer_and_asks_the_realm_inside() -> None:
    env = _env("Deployment", "api", "argos-services")
    assert env["ARGOS_OIDC_ISSUER"] == ISSUER
    assert env["ARGOS_OIDC_INTERNAL_URL"] == "http://keycloak.argos-core.svc:8080/realms/argos"


def _ingress_from(policy: dict[str, Any]) -> list[tuple[Any, list[int]]]:
    return [
        (origin, [p["port"] for p in rule["ports"]])
        for rule in policy["spec"].get("ingress", [])
        for origin in rule["from"]
    ]


def test_traefik_reaches_the_api_and_keycloak_and_nothing_else_of_them() -> None:
    api = _named("NetworkPolicy", "api-from-traefik", "argos-services")
    assert api["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "api"}
    assert _ingress_from(api) == [(TRAEFIK, [8000])]
    verifier = _named("NetworkPolicy", "verifier-from-traefik", "argos-services")
    assert verifier["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "verifier"}
    assert _ingress_from(verifier) == [(TRAEFIK, [8007])]
    keycloak = _named("NetworkPolicy", "keycloak", "argos-core")
    assert (TRAEFIK, [8080]) in _ingress_from(keycloak)


def test_traefik_reaches_the_acme_solvers_while_a_certificate_is_issued() -> None:
    for namespace in ("argos-services", "argos-core"):
        policy = _named("NetworkPolicy", "acme-solver", namespace)
        assert policy["spec"]["podSelector"]["matchLabels"] == {
            "acme.cert-manager.io/http01-solver": "true"
        }
        assert _ingress_from(policy) == [(TRAEFIK, [8089])]
