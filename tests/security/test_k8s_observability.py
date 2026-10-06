"""K-10 · the observability of the bench, inside the cluster only (ARG-091…093).

The same rules, dashboards and Loki of development (one source: the files of the repository, read
by the render of the workflow), and the same route of the alerts: to the console of the API, with
the token of the seeder. Every service pushes its own logs to Loki. Nothing of this has a way in
from outside the cluster.
"""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "platform" / "k8s"
OBS = K8S / "base" / "observability"
LOKI_PUSH = "http://loki.argos-core.svc:3100/loki/api/v1/push"


def _documents(folder: Path) -> list[dict[str, Any]]:
    documents = []
    for path in sorted(folder.rglob("*.yaml")):
        documents += [d for d in yaml.safe_load_all(path.read_text("utf-8")) if isinstance(d, dict)]
    return documents


def _named(kind: str, name: str, folder: Path = K8S / "base") -> dict[str, Any]:
    [found] = [
        d for d in _documents(folder) if d.get("kind") == kind and d["metadata"]["name"] == name
    ]
    return found


def _generated(name: str) -> list[str]:
    kustomization = yaml.safe_load((OBS / "kustomization.yaml").read_text("utf-8"))
    [generator] = [g for g in kustomization["configMapGenerator"] if g["name"] == name]
    files: list[str] = generator["files"]
    return files


def _env(name: str) -> dict[str, Any]:
    pod = _named("Deployment", name)["spec"]["template"]["spec"]
    [container] = [c for c in pod["containers"] if c["name"] == name]
    return {e["name"]: e.get("value", e.get("valueFrom")) for e in container.get("env", [])}


def test_the_base_includes_the_observability_and_the_render_reads_the_repository() -> None:
    base = yaml.safe_load((K8S / "base" / "kustomization.yaml").read_text("utf-8"))
    assert "observability" in base["resources"]
    workflow = (ROOT / ".github" / "workflows" / "bench.yml").read_text("utf-8")
    assert "kubectl kustomize --load-restrictor=LoadRestrictionsNone rendered" in workflow


def test_prometheus_takes_every_rule_of_the_repository() -> None:
    files = {Path(f).name for f in _generated("prometheus-rules")}
    wanted = {p.name for p in (ROOT / "platform" / "observability" / "rules").glob("*.yml")}
    wanted |= {p.name for p in (ROOT / "deploy" / "dev" / "prometheus" / "rules").glob("*.yml")}
    assert files == wanted


def test_prometheus_scrapes_the_api_and_the_health_and_alerts_alertmanager() -> None:
    config = yaml.safe_load((OBS / "prometheus.yml").read_text("utf-8"))
    targets = {
        job["job_name"]: job["static_configs"][0]["targets"] for job in config["scrape_configs"]
    }
    assert targets["argos-api"] == ["api.argos-services.svc:8000"]
    assert targets["argos-health"] == ["health.argos-services.svc:8000"]
    [alertmanagers] = config["alerting"]["alertmanagers"]
    assert alertmanagers["static_configs"][0]["targets"] == ["alertmanager.argos-core.svc:9093"]


def test_the_alerts_follow_the_route_of_development_to_the_console() -> None:
    bench = yaml.safe_load((OBS / "alertmanager.yml").read_text("utf-8"))
    dev = yaml.safe_load(
        (ROOT / "deploy" / "dev" / "alertmanager" / "alertmanager.yml").read_text()
    )
    assert bench["route"] == dev["route"] and bench["inhibit_rules"] == dev["inhibit_rules"]
    [receiver] = bench["receivers"]
    [hook] = receiver["webhook_configs"]
    assert hook["url"] == "http://api.argos-services.svc:8000/internal/alertmanager"
    assert hook["http_config"]["authorization"]["credentials_file"] == (
        "/etc/alertmanager/token/token"
    )


def test_loki_and_the_dashboards_are_the_ones_of_development() -> None:
    assert _generated("loki-config") == ["argos.yaml=../../../../deploy/dev/loki/loki.yaml"]
    files = {Path(f).name for f in _generated("grafana-dashboards")}
    wanted = {p.name for p in (ROOT / "platform" / "observability" / "dashboards").glob("*.json")}
    assert files == wanted


def test_every_service_pushes_its_logs_to_loki() -> None:
    for deployment in _documents(K8S / "base" / "services"):
        if deployment.get("kind") != "Deployment":
            continue
        name = deployment["metadata"]["name"]
        if name == "verifier":
            continue  # it reaches nothing, not even Loki
        assert _env(name)["ARGOS_LOKI_URL"] == LOKI_PUSH, name
        policy = _named("NetworkPolicy", name)
        reached = [
            rule["to"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"]
            for rule in policy["spec"]["egress"]
            if "podSelector" in rule["to"][0]
        ]
        assert "loki" in reached, name


def test_the_api_reads_prometheus_and_takes_the_alerts_with_the_token() -> None:
    env = _env("api")
    assert env["ARGOS_PROMETHEUS_URL"] == "http://prometheus.argos-core.svc:9090"
    assert env["ARGOS_ALERTMANAGER_TOKEN_FILE"] == "/run/secrets/alertmanager/token"
    pod = _named("Deployment", "api")["spec"]["template"]["spec"]
    volumes = {v["name"]: v for v in pod["volumes"]}
    assert volumes["alertmanager-token"]["secret"]["secretName"] == "alertmanager-token"
    wanted = yaml.safe_load((K8S / "base" / "core" / "seeder" / "secrets.yaml").read_text())
    [entry] = [w for w in wanted if w["name"] == "alertmanager-token"]
    assert entry["copy_to"] == ["argos-services"]


def test_only_prometheus_and_alertmanager_reach_the_api_and_the_health_from_core() -> None:
    policy = _named("NetworkPolicy", "observability-in")
    origins = {
        (rule["from"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"], p["port"])
        for rule in policy["spec"]["ingress"]
        for p in rule["ports"]
    }
    assert origins == {("prometheus", 8000), ("alertmanager", 8000)}
    assert policy["spec"]["podSelector"]["matchExpressions"][0]["values"] == ["api", "health"]


def test_nothing_of_the_observability_has_a_way_in_from_outside() -> None:
    for document in _documents(OBS):
        assert document.get("kind") != "Ingress"
        if document.get("kind") == "Service":
            assert document["spec"].get("type", "ClusterIP") == "ClusterIP"


def test_grafana_shows_without_signing_in_but_its_admin_comes_from_the_seeder() -> None:
    env = {
        e["name"]: e.get("value", e.get("valueFrom"))
        for e in _named("Deployment", "grafana")["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert env["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"
    assert env["GF_SECURITY_ADMIN_PASSWORD"] == {
        "secretKeyRef": {"name": "grafana-admin", "key": "password"}
    }
    assert env["GF_ANALYTICS_REPORTING_ENABLED"] == "false"
