"""K-03 · the core of the bench in `argos-core`, validated before it reaches the cluster (DP-22).

Every workload of an ARGOS namespace meets the restricted Pod Security standard that Kubernetes
already enforces there; every image is pinned by digest; whatever keeps data has its volume; and
Vault runs as a server, never in development mode, with no token of any kind in the manifests.
Each component opens its own way in, and only from the namespaces of ARGOS.
"""

from pathlib import Path
from typing import Any

import yaml

K8S = Path(__file__).resolve().parents[2] / "platform" / "k8s"
CORE = K8S / "base" / "core"
ARGOS_NAMESPACES = {"argos-core", "argos-services", "argos-ai", "argos-connect"}
WORKLOADS = {"Deployment", "StatefulSet", "Job", "DaemonSet"}


def _documents(folder: Path) -> list[dict[str, Any]]:
    documents = []
    for path in sorted(folder.rglob("*.yaml")):
        # Only objects of Kubernetes: the seeder keeps its list of secrets as plain YAML.
        documents += [d for d in yaml.safe_load_all(path.read_text("utf-8")) if isinstance(d, dict)]
    return documents


def _workloads() -> list[dict[str, Any]]:
    return [d for d in _documents(K8S / "base") if d.get("kind") in WORKLOADS]


def _pod(workload: dict[str, Any]) -> dict[str, Any]:
    spec: dict[str, Any] = workload["spec"]["template"]["spec"]
    return spec


def _containers(workload: dict[str, Any]) -> list[dict[str, Any]]:
    pod = _pod(workload)
    return [*pod.get("initContainers", []), *pod["containers"]]


def _named(kind: str, name: str) -> dict[str, Any]:
    [found] = [
        d for d in _documents(CORE) if d.get("kind") == kind and d["metadata"]["name"] == name
    ]
    return found


def test_every_workload_meets_the_restricted_standard() -> None:
    workloads = _workloads()
    assert workloads, "no workload yet"
    for workload in workloads:
        name = workload["metadata"]["name"]
        assert workload["metadata"]["namespace"] in ARGOS_NAMESPACES, name
        pod = _pod(workload)
        assert pod["securityContext"]["runAsNonRoot"] is True, name
        assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}, name
        # The token of the service account goes only to the pods that talk to Kubernetes.
        assert pod.get("automountServiceAccountToken") is False or pod.get("serviceAccountName"), (
            name
        )
        for container in _containers(workload):
            context = container["securityContext"]
            assert context["allowPrivilegeEscalation"] is False, (name, container["name"])
            assert context["capabilities"] == {"drop": ["ALL"]}, (name, container["name"])
            assert context["readOnlyRootFilesystem"] is True, (name, container["name"])


def _built_by_the_bench() -> set[str]:
    import importlib.util

    tool = K8S.parents[1] / "tools" / "bench_render.py"
    spec = importlib.util.spec_from_file_location("bench_render", tool)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.ALL_IMAGES)


def test_every_image_is_pinned_by_digest() -> None:
    """Third-party images by digest here; the ones the bench builds, by digest when rendered."""
    built = _built_by_the_bench()
    for workload in _workloads():
        for container in _containers(workload):
            image = container["image"]
            pinned = "@sha256:" in image or image in built
            assert pinned, f"{container['name']}: {image} can move under the tag"


def test_what_keeps_data_keeps_it_in_a_persistent_volume() -> None:
    for workload in _workloads():
        if workload["kind"] == "StatefulSet":
            claims = workload["spec"].get("volumeClaimTemplates", [])
            assert claims, workload["metadata"]["name"]


def test_vault_runs_as_a_server_and_never_in_development_mode() -> None:
    vault = _named("StatefulSet", "vault")
    [container] = _pod(vault)["containers"]
    command = " ".join([*container.get("command", []), *container.get("args", [])])
    assert "server" in command and "-dev" not in command
    names = {e["name"] for e in container.get("env", [])}
    assert not names & {"VAULT_DEV_ROOT_TOKEN_ID", "VAULT_TOKEN", "VAULT_DEV_LISTEN_ADDRESS"}
    config = _named("ConfigMap", "vault-config")["data"]["vault.hcl"]
    assert 'storage "raft"' in config
    assert "disable_mlock = true" in config, "no IPC_LOCK under the restricted standard"
    assert "ui = false" in config


def test_vault_is_ready_even_sealed_so_flux_can_finish_applying() -> None:
    """Sealed or not initialised is the state a person resolves (vault.sh), not a broken pod."""
    [container] = _pod(_named("StatefulSet", "vault"))["containers"]
    path = container["readinessProbe"]["httpGet"]["path"]
    assert "sealedcode=200" in path and "uninitcode=200" in path


def test_only_the_namespaces_of_argos_reach_vault_and_only_on_its_port() -> None:
    policy = _named("NetworkPolicy", "vault")
    assert policy["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "vault"}
    [rule] = policy["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8200}]
    [peer] = rule["from"]
    expression = peer["namespaceSelector"]["matchExpressions"][0]
    assert expression == {
        "key": "kubernetes.io/metadata.name",
        "operator": "In",
        "values": sorted(ARGOS_NAMESPACES),
    }


def test_the_base_includes_the_core() -> None:
    kustomization = yaml.safe_load((K8S / "base" / "kustomization.yaml").read_text("utf-8"))
    assert "core" in kustomization["resources"]


# ---------- the secrets of the cluster are generated in it, never versioned ----------


def test_the_seeder_may_only_read_and_create_secrets_in_argos_core() -> None:
    role = _named("Role", "secret-seeder")
    assert role["metadata"]["namespace"] == "argos-core"
    [rule] = role["rules"]
    assert rule["resources"] == ["secrets"] and sorted(rule["verbs"]) == ["create", "get"]


def test_the_seeder_creates_what_is_missing_and_never_shows_a_value() -> None:
    seeder = CORE / "seeder"
    script = (seeder / "seed.py").read_text(encoding="utf-8")
    assert "secrets.token_urlsafe" in script
    assert "404" in script, "it creates only the secrets that do not exist"
    assert "print(value" not in script and "print(data" not in script
    wanted = yaml.safe_load((seeder / "secrets.yaml").read_text(encoding="utf-8"))
    assert {"name": "postgres-superuser", "keys": ["password"]} in wanted


def test_the_seeder_job_is_recreated_when_it_changes() -> None:
    job = _named("Job", "secret-seeder")
    annotations = job["metadata"]["annotations"]
    assert annotations["kustomize.toolkit.fluxcd.io/force"] == "enabled"
    assert _pod(job)["serviceAccountName"] == "secret-seeder"


# ---------- PostgreSQL with AGE and pgvector ----------


def test_postgres_takes_its_password_from_the_generated_secret() -> None:
    [container] = _pod(_named("StatefulSet", "postgres"))["containers"]
    env = {e["name"]: e for e in container["env"]}
    assert env["POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "postgres-superuser",
        "key": "password",
    }
    assert "value" not in env["POSTGRES_PASSWORD"]
    args = " ".join(container["args"])
    assert "shared_preload_libraries=age" in args


def test_postgres_asks_every_network_client_for_scram() -> None:
    hba = _named("ConfigMap", "postgres-hba")["data"]["pg_hba.conf"]
    rules = [line.split() for line in hba.splitlines() if line and not line.startswith("#")]
    network = [r for r in rules if r[0].startswith("host")]
    assert network and all(r[-1] == "scram-sha-256" for r in network)
    assert not any(r[-1] == "trust" for r in network)


def test_only_the_namespaces_of_argos_reach_postgres() -> None:
    policy = _named("NetworkPolicy", "postgres")
    [rule] = policy["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 5432}]


# ---------- NATS JetStream, one user per service ----------

NATS_USERS = ["inventory", "challenge", "evidence", "webhook", "platform"]


def _nats_conf() -> str:
    conf: str = _named("ConfigMap", "nats-config")["data"]["nats.conf"]
    return conf


def _without_passwords(block: str) -> str:
    return "\n".join(line for line in block.splitlines() if "password" not in line)


def _user_block(conf: str, user: str) -> str:
    return conf.split(f"user: {user}\n", 1)[1].split("\n    }", 1)[0]


def test_nats_keeps_the_users_and_permissions_of_the_development_environment() -> None:
    development = (K8S.parents[1] / "deploy" / "dev" / "nats" / "nats.conf").read_text("utf-8")
    bench = _nats_conf()
    for user in NATS_USERS:
        assert f"user: {user}\n" in bench, user
        dev_block = _user_block(development, user)
        bench_block = _user_block(bench, user)
        assert _without_passwords(bench_block) == _without_passwords(dev_block), user
    assert "argos-dev" not in bench, "the user of the developer's host is not in the bench"


def test_every_nats_password_comes_from_the_generated_secret() -> None:
    conf = _nats_conf()
    assert "dev-only" not in conf
    for user in NATS_USERS:
        assert f"password: $NATS_PASSWORD_{user.upper()}" in conf, user
    [container] = _pod(_named("StatefulSet", "nats"))["containers"]
    env = {e["name"]: e["valueFrom"]["secretKeyRef"] for e in container["env"]}
    for user in NATS_USERS:
        assert env[f"NATS_PASSWORD_{user.upper()}"] == {"name": "nats-users", "key": user}
    wanted = yaml.safe_load((CORE / "seeder" / "secrets.yaml").read_text("utf-8"))
    assert {"name": "nats-users", "keys": NATS_USERS} in wanted


def test_jetstream_keeps_its_streams_in_a_volume() -> None:
    assert "store_dir: /data" in _nats_conf()
    [claim] = _named("StatefulSet", "nats")["spec"]["volumeClaimTemplates"]
    assert claim["metadata"]["name"] == "data"


def test_only_the_namespaces_of_argos_reach_nats() -> None:
    [rule] = _named("NetworkPolicy", "nats")["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 4222}]


# ---------- OPA, the operational rules of the challenge engine (ARG-036) ----------


def test_opa_asks_every_client_for_a_token_it_only_knows_by_its_hash() -> None:
    deployment = _named("Deployment", "opa")
    [container] = _pod(deployment)["containers"]
    args = container["args"]
    assert "--authentication=token" in args and "--authorization=basic" in args
    assert container["image"] == "argos-opa", "policies travel in the signed image, not a mount"
    [init] = _pod(deployment)["initContainers"]
    script = " ".join(init["command"] + init.get("args", []))
    assert "sha256" in script and "opa_clients" in script
    assert "print(token" not in script
    env = {e["name"]: e["valueFrom"]["secretKeyRef"] for e in init["env"]}
    assert env["OPA_TOKEN_CHALLENGE"] == {"name": "opa-clients", "key": "challenge"}
    wanted = yaml.safe_load((CORE / "seeder" / "secrets.yaml").read_text("utf-8"))
    assert {"name": "opa-clients", "keys": ["challenge"]} in wanted


def test_the_image_of_opa_carries_the_policies_of_the_library() -> None:
    dockerfile = (K8S / "images" / "opa" / "Dockerfile").read_text("utf-8")
    assert "openpolicyagent/opa:1.20.2@sha256:" in dockerfile
    for source in ("library/policies", "deploy/dev/opa/client", "deploy/dev/opa-auth/authz.rego"):
        assert source in dockerfile, source
    assert "clients.json" not in dockerfile, "the hashes of the development tokens stay out"


def test_only_the_services_of_argos_reach_opa() -> None:
    [rule] = _named("NetworkPolicy", "opa")["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8181}]
    [peer] = rule["from"]
    assert peer["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "argos-services"
    }


# ---------- Temporal and its own database ----------


def test_temporal_writes_its_configuration_only_in_an_empty_volume() -> None:
    temporal = _named("Deployment", "temporal")
    pod = _pod(temporal)
    [init] = pod["initContainers"]
    [server] = pod["containers"]
    assert init["image"] == server["image"], "the template is copied from the same image"
    mounts = {m["mountPath"]: m["name"] for m in server["volumeMounts"]}
    assert mounts["/etc/temporal/config"] == "config"
    volumes = {v["name"]: v for v in pod["volumes"]}
    assert "emptyDir" in volumes["config"]


def test_temporal_and_its_database_share_a_generated_password() -> None:
    [server] = _pod(_named("Deployment", "temporal"))["containers"]
    env = {e["name"]: e for e in server["env"]}
    assert env["POSTGRES_PWD"]["valueFrom"]["secretKeyRef"] == {
        "name": "temporal-db",
        "key": "password",
    }
    [database] = _pod(_named("StatefulSet", "temporal-db"))["containers"]
    db_env = {e["name"]: e for e in database["env"]}
    assert db_env["POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "temporal-db",
        "key": "password",
    }
    assert "POSTGRES_HOST_AUTH_METHOD" not in db_env, "never trust, as development does"
    wanted = yaml.safe_load((CORE / "seeder" / "secrets.yaml").read_text("utf-8"))
    assert {"name": "temporal-db", "keys": ["password"]} in wanted


def test_only_temporal_reaches_its_database_and_only_argos_services_reach_temporal() -> None:
    [db_rule] = _named("NetworkPolicy", "temporal-db")["spec"]["ingress"]
    [peer] = db_rule["from"]
    assert peer == {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "temporal"}}}
    services, itself = _named("NetworkPolicy", "temporal")["spec"]["ingress"]
    assert services["ports"] == [{"protocol": "TCP", "port": 7233}]
    [frontend] = services["from"]
    assert frontend["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "argos-services"
    }
    # The services of the server talk to each other through the address of the pod.
    assert itself["from"] == [
        {"podSelector": {"matchLabels": {"app.kubernetes.io/name": "temporal"}}}
    ]


# ---------- the WORM store and the test time stamping authority (ARG-061, ARG-065) ----------


def test_the_worm_store_takes_its_keys_from_the_generated_secret() -> None:
    store = _named("StatefulSet", "evidence-store")
    [container] = _pod(store)["containers"]
    script = " ".join(container["command"] + container.get("args", []))
    assert "dev-only" not in script
    env = {e["name"]: e["valueFrom"]["secretKeyRef"] for e in container["env"]}
    assert env["S3_ACCESS_KEY"] == {"name": "evidence-store", "key": "access"}
    assert env["S3_SECRET_KEY"] == {"name": "evidence-store", "key": "secret"}
    assert "--versioning-dir" in script, "object lock needs versions"
    wanted = yaml.safe_load((CORE / "seeder" / "secrets.yaml").read_text("utf-8"))
    assert {"name": "evidence-store", "keys": ["access", "secret"]} in wanted


def test_the_tsa_is_the_test_one_built_by_the_bench() -> None:
    [container] = _pod(_named("StatefulSet", "tsa"))["containers"]
    assert container["image"] == "argos-tsa"
    claims = _named("StatefulSet", "tsa")["spec"]["volumeClaimTemplates"]
    assert claims, "its test CA lives in its volume, never in the repository"


def test_only_the_services_of_argos_reach_the_evidence() -> None:
    for name, port in (("evidence-store", 7070), ("tsa", 3180)):
        [rule] = _named("NetworkPolicy", name)["spec"]["ingress"]
        assert rule["ports"] == [{"protocol": "TCP", "port": port}], name
        [peer] = rule["from"]
        assert peer["namespaceSelector"]["matchLabels"] == {
            "kubernetes.io/metadata.name": "argos-services"
        }, name
