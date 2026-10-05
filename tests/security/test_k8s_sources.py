"""K-07 · the simulated sources of the bench in `bench-sources`, validated before they reach the cluster.

They play the client's systems with the synthetic data of development (F02-04, F02-08, F02-12): the
same SQL, files, directory and clinical records. Their credentials are generated in the cluster by the
seeder, never written here; only the pods of ARGOS that read sources reach them, and they reach
nothing. MSSQL and Oracle (the `heavy` profile, several GB) stay out of the bench.
"""

from pathlib import Path
from typing import Any

import yaml

K8S = Path(__file__).resolve().parents[2] / "platform" / "k8s"
SOURCES_DIR = K8S / "base" / "sources"
NAMESPACE = "bench-sources"
PORTS = {
    "source-postgres": [5432],
    "source-mariadb": [3306],
    "source-smb": [445],
    "source-s3": [7070],
    "source-ldap": [636],
    "source-fhir": [8080],
    "source-dicom": [4242, 8042],
}
READERS = ["challenge-worker", "inventory-scheduler"]


def _documents() -> list[dict[str, Any]]:
    documents = []
    for path in sorted(SOURCES_DIR.rglob("*.yaml")):
        documents += [d for d in yaml.safe_load_all(path.read_text("utf-8")) if isinstance(d, dict)]
    return documents


def _named(kind: str, name: str) -> dict[str, Any]:
    [found] = [d for d in _documents() if d.get("kind") == kind and d["metadata"]["name"] == name]
    return found


def _container(name: str) -> dict[str, Any]:
    pod = _named("Deployment", name)["spec"]["template"]["spec"]
    [container] = [c for c in pod["containers"] if c["name"] == name]
    return container


def test_the_base_includes_the_sources() -> None:
    base = yaml.safe_load((K8S / "base" / "kustomization.yaml").read_text("utf-8"))
    assert "sources" in base["resources"]


def test_each_source_runs_in_bench_sources_with_its_service() -> None:
    for name, ports in PORTS.items():
        assert _named("Deployment", name)["metadata"]["namespace"] == NAMESPACE
        service = _named("Service", name)
        assert sorted(p["port"] for p in service["spec"]["ports"]) == ports, name


def test_no_credential_is_written_here() -> None:
    text = "\n".join(p.read_text("utf-8") for p in sorted(SOURCES_DIR.rglob("*.yaml")))
    assert "dev-only" not in text
    assert "MARIADB_ALLOW_EMPTY_ROOT_PASSWORD" not in text
    for name, key in [
        ("source-smb", "ACCOUNT_argos_ro"),
        ("source-ldap", "LDAP_READONLY_USER_PASSWORD"),
        ("source-ldap", "LDAP_ADMIN_PASSWORD"),
    ]:
        env = {e["name"]: e for e in _container(name)["env"]}
        assert env[key]["valueFrom"]["secretKeyRef"]["name"] == "bench-sources", (name, key)


def test_the_directory_speaks_ldaps_with_a_certificate_of_the_bench() -> None:
    spec = _named("Certificate", "source-ldap")["spec"]
    assert spec["secretName"] == "source-ldap-tls"
    assert "source-ldap.bench-sources.svc" in spec["dnsNames"]
    assert spec["issuerRef"] == {"name": "vault-bench", "kind": "ClusterIssuer"}
    setup = (K8S / "bench" / "vault-setup.sh").read_text("utf-8")
    assert "bench-sources.svc" in setup.split("allowed_domains=", 1)[1].split()[0]


def test_only_the_readers_of_argos_reach_each_source() -> None:
    for name, ports in PORTS.items():
        policy = _named("NetworkPolicy", name)
        assert policy["spec"]["podSelector"]["matchLabels"] == {"app.kubernetes.io/name": name}
        readers = set()
        for rule in policy["spec"]["ingress"]:
            for origin in rule["from"]:
                if "namespaceSelector" in origin:
                    assert origin["namespaceSelector"]["matchLabels"] == {
                        "kubernetes.io/metadata.name": "argos-services"
                    }
                    [expression] = origin["podSelector"]["matchExpressions"]
                    readers.update(expression["values"])
                else:
                    assert origin["podSelector"]["matchLabels"] == {
                        "app.kubernetes.io/name": "clinical-seed"
                    }, "inside the namespace only the seeder"
        assert sorted(readers) == READERS, name


def test_the_clinical_seeder_reaches_only_fhir_and_dicom() -> None:
    policy = _named("NetworkPolicy", "clinical-seed")
    reached = {
        (rule["to"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"], p["port"])
        for rule in policy["spec"]["egress"]
        for p in rule["ports"]
    }
    assert reached == {("source-fhir", 8080), ("source-dicom", 8042)}


def test_the_seeder_creates_the_credentials_of_the_sources_where_they_are_used() -> None:
    wanted = yaml.safe_load((K8S / "base" / "core" / "seeder" / "secrets.yaml").read_text("utf-8"))
    [entry] = [w for w in wanted if w["name"] == "bench-sources"]
    assert entry["copy_to"] == ["bench-sources"]
    assert set(entry["keys"]) == {"smb", "s3-access", "s3-secret", "ldap-admin", "ldap-ro"}
