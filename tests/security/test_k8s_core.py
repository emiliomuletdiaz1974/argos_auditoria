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


def _container(workload: dict[str, Any], name: str) -> dict[str, Any]:
    [found] = [c for c in _pod(workload)["containers"] if c["name"] == name]
    return found


def _named(kind: str, name: str, namespace: str | None = None) -> dict[str, Any]:
    [found] = [
        d
        for d in _documents(K8S / "base")
        if d.get("kind") == kind
        and d["metadata"]["name"] == name
        and namespace in (None, d["metadata"].get("namespace"))
    ]
    return found


def test_every_workload_meets_the_restricted_standard() -> None:
    workloads = _workloads()
    assert workloads, "no workload yet"
    for workload in workloads:
        name = workload["metadata"]["name"]
        if workload["metadata"]["namespace"] == "bench-sources":
            continue  # the simulated client: baseline, below
        assert workload["metadata"]["namespace"] in ARGOS_NAMESPACES, name
        pod = _pod(workload)
        assert pod["securityContext"]["runAsNonRoot"] is True, name
        seccomp = pod["securityContext"]["seccompProfile"]
        # RuntimeDefault, or a profile of ARGOS loaded on the node (K-09, platform/k8s/security).
        assert seccomp == {"type": "RuntimeDefault"} or (
            seccomp["type"] == "Localhost" and seccomp["localhostProfile"].startswith("argos/")
        ), name
        # The token of the service account goes only to the pods that talk to Kubernetes.
        assert pod.get("automountServiceAccountToken") is False or pod.get("serviceAccountName"), (
            name
        )
        for container in _containers(workload):
            context = container["securityContext"]
            assert context["allowPrivilegeEscalation"] is False, (name, container["name"])
            assert context["capabilities"] == {"drop": ["ALL"]}, (name, container["name"])
            assert context["readOnlyRootFilesystem"] is True, (name, container["name"])


def test_the_simulated_sources_meet_the_baseline_standard() -> None:
    """K-07: third-party images of the simulated client (Samba, OpenLDAP, Orthanc) start as root,
    which bench-sources admits (baseline); nothing privileged, nothing of the node."""
    sources = [w for w in _workloads() if w["metadata"]["namespace"] == "bench-sources"]
    assert sources
    for workload in sources:
        name = workload["metadata"]["name"]
        pod = _pod(workload)
        assert pod["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}, name
        assert pod["automountServiceAccountToken"] is False, name
        for key in ("hostNetwork", "hostPID", "hostIPC"):
            assert not pod.get(key), (name, key)
        assert all("hostPath" not in v for v in pod.get("volumes", [])), name
        for container in _containers(workload):
            context = container.get("securityContext", {})
            assert not context.get("privileged"), (name, container["name"])
            assert "add" not in context.get("capabilities", {}), (name, container["name"])


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
    # The namespaces of ARGOS, and cert-manager, which signs in to sign certificates (K-04).
    assert expression == {
        "key": "kubernetes.io/metadata.name",
        "operator": "In",
        "values": sorted(ARGOS_NAMESPACES | {"cert-manager"}),
    }


def test_the_base_includes_the_core() -> None:
    kustomization = yaml.safe_load((K8S / "base" / "kustomization.yaml").read_text("utf-8"))
    assert "core" in kustomization["resources"]


# ---------- the secrets of the cluster are generated in it, never versioned ----------


def test_the_seeder_may_only_read_and_create_secrets_in_argos_core() -> None:
    role = _named("Role", "secret-seeder", "argos-core")
    [rule] = role["rules"]
    assert rule["resources"] == ["secrets"] and sorted(rule["verbs"]) == ["create", "get"]


def test_the_seeder_may_only_read_and_create_the_copies_in_argos_services() -> None:
    """K-06: the copies of the secrets the services sign in with, and nothing more."""
    role = _named("Role", "secret-seeder", "argos-services")
    [rule] = role["rules"]
    assert rule["resources"] == ["secrets"] and sorted(rule["verbs"]) == ["create", "get"]
    binding = _named("RoleBinding", "secret-seeder", "argos-services")
    assert binding["subjects"] == [
        {"kind": "ServiceAccount", "name": "secret-seeder", "namespace": "argos-core"}
    ]


def test_the_seeder_creates_what_is_missing_and_never_shows_a_value() -> None:
    seeder = CORE / "seeder"
    script = (seeder / "seed.py").read_text(encoding="utf-8")
    assert "secrets.token_urlsafe" in script
    assert "404" in script, "it creates only the secrets that do not exist"
    assert "print(value" not in script and "print(data" not in script
    wanted = yaml.safe_load((seeder / "secrets.yaml").read_text(encoding="utf-8"))
    assert {"name": "postgres-superuser", "keys": ["password"]} in wanted
    copied = {w["name"] for w in wanted if w.get("copy_to")}
    assert copied == {
        "nats-users",
        "opa-clients",
        "evidence-store",
        "bench-sources",
        "alertmanager-token",
    }


def test_the_seeder_job_is_recreated_when_it_changes() -> None:
    job = _named("Job", "secret-seeder")
    annotations = job["metadata"]["annotations"]
    assert annotations["kustomize.toolkit.fluxcd.io/force"] == "enabled"
    assert _pod(job)["serviceAccountName"] == "secret-seeder"


# ---------- PostgreSQL with AGE and pgvector ----------


def test_postgres_takes_its_password_from_the_generated_secret() -> None:
    container = _container(_named("StatefulSet", "postgres"), "postgres")
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
    over_tls = [r for r in rules if r[0] == "hostssl"]
    assert over_tls and all(r[-1] == "scram-sha-256" for r in over_tls)
    assert not any(r[-1] == "trust" for r in rules if r[0].startswith("host"))


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
    container = _container(_named("StatefulSet", "nats"), "nats")
    env = {e["name"]: e["valueFrom"]["secretKeyRef"] for e in container["env"]}
    for user in NATS_USERS:
        assert env[f"NATS_PASSWORD_{user.upper()}"] == {"name": "nats-users", "key": user}
    wanted = yaml.safe_load((CORE / "seeder" / "secrets.yaml").read_text("utf-8"))
    assert {"name": "nats-users", "keys": NATS_USERS, "copy_to": ["argos-services"]} in wanted


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
    assert {"name": "opa-clients", "keys": ["challenge"], "copy_to": ["argos-services"]} in wanted


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
    container = _container(store, "versitygw")
    script = " ".join(container["command"] + container.get("args", []))
    assert "dev-only" not in script
    env = {e["name"]: e["valueFrom"]["secretKeyRef"] for e in container["env"]}
    assert env["S3_ACCESS_KEY"] == {"name": "evidence-store", "key": "access"}
    assert env["S3_SECRET_KEY"] == {"name": "evidence-store", "key": "secret"}
    assert "--versioning-dir" in script, "object lock needs versions"
    wanted = yaml.safe_load((CORE / "seeder" / "secrets.yaml").read_text("utf-8"))
    assert {
        "name": "evidence-store",
        "keys": ["access", "secret"],
        "copy_to": ["argos-services"],
    } in wanted


def test_the_tsa_is_the_test_one_built_by_the_bench() -> None:
    [container] = _pod(_named("StatefulSet", "tsa"))["containers"]
    assert container["image"] == "argos-tsa"
    claims = _named("StatefulSet", "tsa")["spec"]["volumeClaimTemplates"]
    assert claims, "its test CA lives in its volume, never in the repository"


def test_only_the_services_of_argos_reach_the_evidence() -> None:
    for name, port in (("evidence-store", 7070), ("tsa", 3180)):
        rule = _named("NetworkPolicy", name)["spec"]["ingress"][0]
        assert rule["ports"] == [{"protocol": "TCP", "port": port}], name
        [peer] = rule["from"]
        assert peer["namespaceSelector"]["matchLabels"] == {
            "kubernetes.io/metadata.name": "argos-services"
        }, name


def test_vault_may_review_tokens_of_service_accounts_and_nothing_more() -> None:
    pod = _pod(_named("StatefulSet", "vault"))
    assert pod["serviceAccountName"] == "vault" and pod["automountServiceAccountToken"] is True
    binding = _named("ClusterRoleBinding", "vault-token-review")
    assert binding["roleRef"]["name"] == "system:auth-delegator"
    assert binding["subjects"] == [
        {"kind": "ServiceAccount", "name": "vault", "namespace": "argos-core"}
    ]
    egress = _named("NetworkPolicy", "vault")["spec"]["egress"]
    assert {
        "ports": [{"protocol": "TCP", "port": 443}, {"protocol": "TCP", "port": 6443}]
    } in egress


def test_vault_reaches_postgres_for_the_dynamic_credentials() -> None:
    """Seen on the bench (banco-v0.8.1): with only the API of Kubernetes open, the database engine
    could not verify its connection and the bootstrap got a 400."""
    egress = _named("NetworkPolicy", "vault")["spec"]["egress"]
    assert {
        "to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "postgres"}}}],
        "ports": [{"protocol": "TCP", "port": 5432}],
    } in egress


# ---------- the bootstrap Job (K-04) ----------


def test_the_bootstrap_runs_from_the_image_of_the_api_with_only_generated_secrets() -> None:
    job = _named("Job", "argos-bootstrap")
    assert job["metadata"]["annotations"]["kustomize.toolkit.fluxcd.io/force"] == "enabled"
    pod = _pod(job)
    assert pod["serviceAccountName"] == "argos-bootstrap"
    [container] = pod["containers"]
    assert container["image"] == "argos-api"
    env = {e["name"]: e["valueFrom"]["secretKeyRef"] for e in container["env"] if "valueFrom" in e}
    assert env == {
        "ARGOS_PG_PASSWORD": {"name": "postgres-superuser", "key": "password"},
        "ARGOS_NATS_PLATFORM_PASSWORD": {"name": "nats-users", "key": "platform"},
        "ARGOS_KEYCLOAK_DB_PASSWORD": {"name": "keycloak-db", "key": "password"},
        # K-07: the credentials of the simulated sources, for Vault
        "ARGOS_SOURCE_SMB_PASSWORD": {"name": "bench-sources", "key": "smb"},
        "ARGOS_SOURCE_S3_ACCESS": {"name": "bench-sources", "key": "s3-access"},
        "ARGOS_SOURCE_S3_SECRET": {"name": "bench-sources", "key": "s3-secret"},
        "ARGOS_SOURCE_LDAP_PASSWORD": {"name": "bench-sources", "key": "ldap-ro"},
    }


def test_the_bootstrap_reaches_only_postgres_nats_and_vault() -> None:
    egress = _named("NetworkPolicy", "argos-bootstrap")["spec"]["egress"]
    reached = {
        (rule["to"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"], p["port"])
        for rule in egress
        for p in rule["ports"]
    }
    assert reached == {("postgres", 5432), ("nats", 4222), ("vault", 8200)}


def test_vault_lets_the_bootstrap_touch_only_the_database_engine() -> None:
    setup = (K8S / "bench" / "vault-setup.sh").read_text("utf-8")
    assert "vault policy write argos-bootstrap" in setup
    policy = setup.split("argos-bootstrap -", 1)[0].rsplit("printf", 1)[1]
    paths = [chunk.split('"')[1] for chunk in policy.split("path ")[1:]]
    # K-07: the sources; K-99: the signed content (only the key argos-content).
    allowed = (
        "sys/mounts",
        "sys/mounts/db",
        "argos/data/connectors/*",
        "transit/sign/argos-content",
        "transit/keys/argos-content",
    )
    assert all(p in allowed or p.startswith("db/") for p in paths), paths
    assert (
        "auth/kubernetes/role/bootstrap bound_service_account_names=argos-bootstrap"
        " bound_service_account_namespaces=argos-core"
    ) in setup


# ---------- TLS of PostgreSQL with cert-manager and Vault (K-04, ahead of K-06) ----------


def test_cert_manager_signs_with_the_intermediate_of_the_bench() -> None:
    issuer = _named("ClusterIssuer", "vault-bench")
    vault = issuer["spec"]["vault"]
    assert vault["path"] == "pki_int/sign/argos-svc"
    assert vault["auth"]["kubernetes"]["role"] == "cert-manager"
    assert vault["auth"]["kubernetes"]["serviceAccountRef"]["name"] == "cert-manager"


def test_postgres_has_a_certificate_with_the_names_of_the_cluster() -> None:
    certificate = _named("Certificate", "postgres")
    spec = certificate["spec"]
    assert spec["secretName"] == "postgres-tls"
    assert set(spec["dnsNames"]) == {
        "postgres.argos-core.svc",
        "postgres.argos-core.svc.cluster.local",
    }
    assert spec["issuerRef"] == {"name": "vault-bench", "kind": "ClusterIssuer"}
    assert spec["privateKey"]["rotationPolicy"] == "Always"


def test_postgres_speaks_only_tls_on_the_network() -> None:
    container = _container(_named("StatefulSet", "postgres"), "postgres")
    args = " ".join(container["args"])
    assert "ssl=on" in args and "ssl_min_protocol_version=TLSv1.3" in args
    hba = _named("ConfigMap", "postgres-hba")["data"]["pg_hba.conf"]
    rules = [line.split() for line in hba.splitlines() if line and not line.startswith("#")]
    assert [r for r in rules if r[0] == "host"] == [], "no clear connection over the network"
    assert ["hostnossl", "all", "all", "all", "reject"] in rules
    volumes = {v["name"]: v for v in _pod(_named("StatefulSet", "postgres"))["volumes"]}
    # PostgreSQL takes a key owned by root only with mode 0640 or less.
    assert volumes["tls"]["secret"] == {"secretName": "postgres-tls", "defaultMode": 0o640}


def test_cert_manager_reaches_vault_and_may_ask_for_its_own_token() -> None:
    [rule] = _named("NetworkPolicy", "vault")["spec"]["ingress"]
    allowed = rule["from"][0]["namespaceSelector"]["matchExpressions"][0]["values"]
    assert "cert-manager" in allowed
    role = _named("Role", "cert-manager-vault-token")
    assert role["metadata"]["namespace"] == "cert-manager"
    [permission] = role["rules"]
    assert permission == {
        "apiGroups": [""],
        "resources": ["serviceaccounts/token"],
        "resourceNames": ["cert-manager"],
        "verbs": ["create"],
    }


def test_vault_reads_the_ca_of_postgres_without_waiting_for_it() -> None:
    """Optional: cert-manager needs Vault to issue that very certificate."""
    pod = _pod(_named("StatefulSet", "vault"))
    volumes = {v["name"]: v for v in pod["volumes"]}
    assert volumes["postgres-ca"]["secret"] == {
        "secretName": "postgres-tls",
        "optional": True,
        "items": [{"key": "ca.crt", "path": "ca.crt"}],
    }
    [container] = pod["containers"]
    mounts = {m["mountPath"]: m for m in container["volumeMounts"]}
    assert mounts["/run/postgres-ca"]["readOnly"] is True


# ---------- Keycloak in production mode (K-05) ----------


def test_keycloak_starts_prebuilt_for_postgres_with_the_bench_realm() -> None:
    [container] = _pod(_named("Deployment", "keycloak"))["containers"]
    assert container["image"] == "argos-keycloak"
    args = container["args"]
    assert args[0] == "start" and "--optimized" in args and "--import-realm" in args
    assert "start-dev" not in args
    env = {e["name"]: e for e in container["env"]}
    assert "sslmode=verify-full" in env["KC_DB_URL"]["value"]
    assert env["KC_DB_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "keycloak-db",
        "key": "password",
    }
    assert env["KC_BOOTSTRAP_ADMIN_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "keycloak-admin",
        "key": "password",
    }
    dockerfile = (K8S / "images" / "keycloak" / "Dockerfile").read_text("utf-8")
    assert "kc.sh build" in dockerfile and "KC_DB=postgres" in dockerfile


def test_keycloak_is_reached_only_by_argos_services_and_reaches_only_postgres() -> None:
    policy = _named("NetworkPolicy", "keycloak")["spec"]
    rule = policy["ingress"][0]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8080}]
    assert rule["from"][0]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "argos-services"
    }
    assert policy["egress"] == [
        {
            "to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "postgres"}}}],
            "ports": [{"protocol": "TCP", "port": 5432}],
        }
    ]


def test_the_bootstrap_gives_keycloak_its_own_database() -> None:
    [container] = _pod(_named("Job", "argos-bootstrap"))["containers"]
    env = {e["name"]: e for e in container["env"]}
    assert env["ARGOS_KEYCLOAK_DB_PASSWORD"]["valueFrom"]["secretKeyRef"] == {
        "name": "keycloak-db",
        "key": "password",
    }
    wanted = yaml.safe_load((CORE / "seeder" / "secrets.yaml").read_text("utf-8"))
    assert {"name": "keycloak-db", "keys": ["password"]} in wanted
    assert {"name": "keycloak-admin", "keys": ["password"]} in wanted


# ---------- the accounts of the bench (K-05) ----------


def test_the_accounts_job_may_only_read_and_create_secrets() -> None:
    role = _named("Role", "keycloak-accounts")
    [rule] = role["rules"]
    assert rule["resources"] == ["secrets"] and sorted(rule["verbs"]) == ["create", "get"]
    pod = _pod(_named("Job", "keycloak-accounts"))
    assert pod["serviceAccountName"] == "keycloak-accounts"
    [container] = pod["containers"]
    env = {e["name"]: e["valueFrom"]["secretKeyRef"] for e in container["env"] if "valueFrom" in e}
    assert env == {"KEYCLOAK_ADMIN_PASSWORD": {"name": "keycloak-admin", "key": "password"}}


def test_the_accounts_job_reaches_keycloak_and_keycloak_lets_it_in() -> None:
    egress = _named("NetworkPolicy", "keycloak-accounts")["spec"]["egress"]
    assert {
        "to": [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "keycloak"}}}],
        "ports": [{"protocol": "TCP", "port": 8080}],
    } in egress
    sources = _named("NetworkPolicy", "keycloak")["spec"]["ingress"]
    assert {
        "from": [{"podSelector": {"matchLabels": {"app.kubernetes.io/name": "keycloak-accounts"}}}],
        "ports": [{"protocol": "TCP", "port": 8080}],
    } in sources


# ---------- The services of argos-services sign in to Vault with their own account (K-06) ---------

SERVICE_POLICIES = {
    "api": {
        ("db/creds/svc-api", ("read",)),
        ("argos/data/webhooks/*", ("create", "read", "update")),
        ("argos/data/services/api/*", ("read",)),
        ("transit/sign/argos-evidence", ("update",)),
        ("transit/keys/argos-evidence", ("read",)),
    },
    "webhook": {
        ("db/creds/svc-webhook", ("read",)),
        ("argos/data/webhooks/*", ("read",)),
    },
    "challenge": {
        ("db/creds/svc-challenge", ("read",)),
        ("argos/data/connectors/*", ("read",)),
        ("argos/data/services/challenge/*", ("read",)),
    },
    "evidence": {
        ("db/creds/svc-evidence", ("read",)),
        ("transit/sign/argos-evidence", ("update",)),
        ("transit/keys/argos-evidence", ("read",)),
    },
    "health": {
        ("db/creds/svc-health", ("read",)),
        ("pki_int/certs", ("list",)),
        ("pki_int/cert/*", ("read",)),
    },
    "verifier-trust": {("transit/keys/argos-evidence", ("read",))},
    # K-07: the inventory reads the credentials of the connectors to scan the sources.
    "inventory": {
        ("db/creds/svc-inventory", ("read",)),
        ("argos/data/connectors/*", ("read",)),
        ("argos/data/services/inventory/*", ("read",)),
    },
}


def _service_policies() -> dict[str, set[tuple[str, tuple[str, ...]]]]:
    import re

    setup = (K8S / "bench" / "vault-setup.sh").read_text("utf-8")
    found = {}
    for name, body in re.findall(r"service_role (\S+) <<'POLICY'\n(.*?)\nPOLICY", setup, re.S):
        rules = re.findall(r'path "([^"]+)" \{ capabilities = \[([^\]]*)\] \}', body)
        found[name] = {
            (path, tuple(sorted(c.strip().strip('"') for c in caps.split(","))))
            for path, caps in rules
        }
    return found


def test_each_service_reads_from_vault_only_what_it_uses() -> None:
    assert _service_policies() == SERVICE_POLICIES


def test_each_vault_role_is_bound_to_its_own_account_in_argos_services() -> None:
    setup = (K8S / "bench" / "vault-setup.sh").read_text("utf-8")
    function = setup.split("service_role() {", 1)[1].split("\n}", 1)[0]
    assert 'bound_service_account_names="$1"' in function
    assert "bound_service_account_namespaces=argos-services" in function
    assert 'policies="k8s-$1"' in function
    # A lease dies with the token that asked for it: the token lives as long as the longest
    # database credential (72 h, bootstrap.py).
    assert "ttl=72h" in function and "max_ttl=72h" in function


# ---------- TLS of NATS and the reload of renewed certificates (K-06) ----------


def test_nats_speaks_tls_and_asks_each_client_for_its_certificate() -> None:
    conf = _nats_conf()
    tls = conf.split("tls {", 1)[1].split("}", 1)[0]
    assert 'cert_file: "/run/tls/tls.crt"' in tls and 'key_file: "/run/tls/tls.key"' in tls
    assert 'ca_file: "/run/tls/ca.crt"' in tls
    assert "verify: true" in tls and 'min_version: "1.3"' in tls
    spec = _named("Certificate", "nats")["spec"]
    assert spec["secretName"] == "nats-tls"
    assert set(spec["dnsNames"]) == {"nats.argos-core.svc", "nats.argos-core.svc.cluster.local"}
    volumes = {v["name"]: v for v in _pod(_named("StatefulSet", "nats"))["volumes"]}
    assert volumes["tls"]["secret"]["secretName"] == "nats-tls"


def test_postgres_rereads_its_certificate_when_cert_manager_renews_it() -> None:
    """Renewed at day 20 of 30: without a reload the server would serve an expired one."""
    pod = _pod(_named("StatefulSet", "postgres"))
    [reload] = [c for c in pod["containers"] if c["name"] == "tls-reload"]
    script = " ".join(reload["command"])
    assert "pg_reload_conf()" in script and "/tls/tls.crt" in script
    mounts = {m["mountPath"] for m in reload["volumeMounts"]}
    assert {"/tls", "/var/run/postgresql"} <= mounts, "the certificate and the local socket"


def test_nats_rereads_its_certificate_when_cert_manager_renews_it() -> None:
    pod = _pod(_named("StatefulSet", "nats"))
    assert pod["shareProcessNamespace"] is True, "the reloader signals the server"
    [reload] = [c for c in pod["containers"] if c["name"] == "tls-reload"]
    script = " ".join(reload["command"])
    assert "kill -HUP" in script and "/run/tls/tls.crt" in script


def test_the_bootstrap_signs_in_to_nats_with_its_own_certificate() -> None:
    spec = _named("Certificate", "bootstrap")["spec"]
    assert spec["secretName"] == "bootstrap-tls" and "client auth" in spec["usages"]
    pod = _pod(_named("Job", "argos-bootstrap"))
    volumes = {v["name"]: v for v in pod["volumes"]}
    assert volumes["tls"]["secret"]["secretName"] == "bootstrap-tls"
    script = (CORE / "bootstrap" / "bootstrap.py").read_text("utf-8")
    assert 'NATS_URL = "tls://nats.argos-core.svc:4222"' in script
    assert "load_cert_chain" in script


def test_only_the_health_service_reads_how_full_the_evidence_volume_is() -> None:
    """K-99: the helper next to the store says used and total, read-only, to the health service."""
    store = _named("StatefulSet", "evidence-store")
    usage = _container(store, "usage")
    assert usage["command"] == ["python", "/usage/usage.py"]
    mounts = {m["name"]: m for m in usage["volumeMounts"]}
    assert mounts["data"]["readOnly"] is True
    [_, rule] = _named("NetworkPolicy", "evidence-store")["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 9101}]
    [peer] = rule["from"]
    assert peer["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": "health"}
