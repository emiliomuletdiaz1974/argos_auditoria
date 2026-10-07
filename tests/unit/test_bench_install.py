"""K-02F · the one-time installation of the bench VM: k3s and Flux, pinned and verified (DP-21).

A person runs `platform/k8s/bench/install.sh` once on the VM. Every download is checked against a
SHA-256 written here before it runs, and nothing is piped into a shell. Flux then pulls the
manifests the workflow `bench.yml` signed, and refuses any artifact that workflow did not sign
from a bench tag.
"""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "platform" / "k8s" / "bench" / "install.sh"
FLUX = ROOT / "platform" / "k8s" / "flux"
WORKFLOW = ROOT / ".github" / "workflows" / "bench.yml"
REPOSITORY = "emiliomuletdiaz1974/argos_auditoria"
SIGNER = f"https://github.com/{REPOSITORY}/.github/workflows/bench.yml@refs/tags/banco-v0.1.0"


def _script() -> str:
    return INSTALL.read_text(encoding="utf-8")


def _flux(kind: str) -> dict[str, Any]:
    documents = []
    for path in sorted(FLUX.glob("*.yaml")):
        documents += [d for d in yaml.safe_load_all(path.read_text("utf-8")) if d]
    # `kustomization.yaml` is kustomize's own Kustomization, not Flux's.
    [found] = [
        d
        for d in documents
        if d.get("kind") == kind and not d["apiVersion"].startswith("kustomize.config.k8s.io")
    ]
    return found


def _pinned(name: str) -> str:
    match = re.search(rf'^{name}="([^"]+)"$', _script(), re.MULTILINE)
    assert match, f"{name} is not pinned in install.sh"
    return match.group(1)


def test_k3s_and_flux_are_pinned_with_their_checksums() -> None:
    assert re.fullmatch(r"v\d+\.\d+\.\d+\+k3s\d+", _pinned("K3S_VERSION"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", _pinned("FLUX_VERSION"))
    for name in ("K3S_INSTALLER_SHA256", "FLUX_SHA256"):
        assert re.fullmatch(r"[0-9a-f]{64}", _pinned(name)), name


def test_the_flux_of_the_vm_is_the_one_that_publishes() -> None:
    assert f"flux2/action@v{_pinned('FLUX_VERSION')}" in WORKFLOW.read_text(encoding="utf-8")


def test_every_download_is_checked_before_it_is_used() -> None:
    script = _script()
    assert not re.search(r"\|\s*(sudo\s+)?(ba)?sh\b", script), "nothing is piped into a shell"
    downloads = re.findall(r'curl [^\n]*-o "([^"]+)"', script)
    assert len(downloads) == 4, "k3s, flux, cert-manager and kyverno"
    checks = [line for line in script.splitlines() if "sha256sum -c" in line]
    for target in downloads:
        assert any(target in line for line in checks), f"{target} is used without its checksum"


def test_the_secrets_of_k3s_are_encrypted_at_rest() -> None:
    assert "--secrets-encryption" in _script()


def _bash() -> str | None:
    """A bash that runs: on Windows `bash` may be the launcher of WSL with no distribution."""
    candidates = [shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            ran = subprocess.run(  # noqa: S603
                [candidate, "-c", "echo ok"], capture_output=True, text=True, check=False
            )
            if ran.stdout.strip() == "ok":
                return candidate
    return None


def _status() -> str:
    return subprocess.run(  # noqa: S603
        ["git", "status", "--porcelain", "--untracked-files=all"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout


BASH = _bash()


@pytest.mark.skipif(BASH is None, reason="no working bash here")
def test_the_script_is_valid_bash_and_a_dry_run_changes_nothing() -> None:
    assert BASH is not None
    script = INSTALL.relative_to(ROOT).as_posix()
    subprocess.run([BASH, "-n", script], check=True, cwd=ROOT)  # noqa: S603
    before = _status()
    answer = subprocess.run(  # noqa: S603
        [BASH, script, "--dry-run"], capture_output=True, text=True, check=True, cwd=ROOT
    )
    planned = answer.stdout
    assert "k3s" in planned and "flux install" in planned and "platform/k8s/flux" in planned
    assert _status() == before, "a dry run writes nothing"


def test_flux_pulls_the_artifact_the_workflow_publishes() -> None:
    source = _flux("OCIRepository")
    owner = REPOSITORY.split("/")[0]
    assert source["spec"]["url"] == f"oci://ghcr.io/{owner}/argos-bench"
    assert "argos-bench" in WORKFLOW.read_text(encoding="utf-8")
    assert "semver" in source["spec"]["ref"], "only versions, never a moving tag"


def test_flux_applies_only_what_bench_yml_signed_from_a_bench_tag() -> None:
    verify = _flux("OCIRepository")["spec"]["verify"]
    assert verify["provider"] == "cosign"
    [identity] = verify["matchOIDCIdentity"]
    assert re.fullmatch(identity["issuer"], "https://token.actions.githubusercontent.com")
    assert re.fullmatch(identity["subject"], SIGNER)
    for forged in (
        SIGNER.replace("refs/tags/banco-v0.1.0", "refs/heads/main"),
        SIGNER.replace("bench.yml", "ci.yml"),
        SIGNER.replace(REPOSITORY, "someone/fork"),
        SIGNER.replace("banco-v0.1.0", "v1.0.0"),
    ):
        assert not re.fullmatch(identity["subject"], forged), forged


def test_flux_removes_what_leaves_the_manifests() -> None:
    sync = _flux("Kustomization")
    assert sync["apiVersion"].startswith("kustomize.toolkit.fluxcd.io/")
    assert sync["spec"]["sourceRef"] == {"kind": "OCIRepository", "name": "argos-bench"}
    assert sync["spec"]["prune"] is True


VAULT_SH = ROOT / "platform" / "k8s" / "bench" / "vault.sh"


def test_the_unseal_keys_go_to_the_console_and_nowhere_else() -> None:
    script = VAULT_SH.read_text(encoding="utf-8")
    [init] = [line for line in script.splitlines() if "operator init" in line]
    assert ">" not in init.split("operator init", 1)[1], "the keys are never written to a file"
    assert "tee" not in script and "kubectl create secret" not in script
    assert "-key-threshold" in init and "-key-shares" in init


def test_init_refuses_a_vault_that_is_already_initialised() -> None:
    script = VAULT_SH.read_text(encoding="utf-8")
    init_block = script.split("  init)", 1)[1].split(";;", 1)[0]
    assert init_block.index("if initialised") < init_block.index("operator init")


@pytest.mark.skipif(BASH is None, reason="no working bash here")
def test_the_vault_script_is_valid_bash() -> None:
    assert BASH is not None
    script = VAULT_SH.relative_to(ROOT).as_posix()
    subprocess.run([BASH, "-n", script], check=True, cwd=ROOT)  # noqa: S603


SETUP_SH = ROOT / "platform" / "k8s" / "bench" / "vault-setup.sh"


def test_configure_asks_for_the_root_token_without_showing_or_keeping_it() -> None:
    script = VAULT_SH.read_text(encoding="utf-8")
    block = script.split("  configure)", 1)[1].split(";;", 1)[0]
    assert "read -rs" in block, "the token is typed without echo"
    assert "vault-setup.sh" in block
    # It reaches Vault through standard input, never as an argument or a variable of the host.
    assert "exec -i" in block and "sh -s" in block
    for line in block.splitlines():
        if "exec" in line:
            assert "$token" not in line, f"the token would be an argument: {line.strip()}"
    assert "unset token" in block


def test_the_setup_of_the_bench_is_the_one_of_development_with_kubernetes_auth() -> None:
    setup = SETUP_SH.read_text(encoding="utf-8")
    assert "dev-only" not in setup and "-dev" not in setup
    for line in (
        "secrets enable -path=argos kv-v2",
        "for key in argos-release argos-content argos-evidence; do",
        '"transit/keys/$key" type=ed25519',
        "pki_int/roles/argos-svc",
        "auth enable kubernetes",
        "auth/kubernetes/config",
    ):
        assert line in setup, line
    assert "exportable=true" not in setup, "no signing key leaves Vault"


@pytest.mark.skipif(BASH is None, reason="no working bash here")
def test_the_setup_script_is_valid_sh() -> None:
    assert BASH is not None
    script = SETUP_SH.relative_to(ROOT).as_posix()
    subprocess.run([BASH, "-n", script], check=True, cwd=ROOT)  # noqa: S603


def test_cert_manager_is_installed_once_pinned_and_verified() -> None:
    assert re.fullmatch(r"v\d+\.\d+\.\d+", _pinned("CERT_MANAGER_VERSION"))
    assert re.fullmatch(r"[0-9a-f]{64}", _pinned("CERT_MANAGER_SHA256"))


def test_vault_lets_cert_manager_only_sign_certificates() -> None:
    setup = SETUP_SH.read_text(encoding="utf-8")
    assert (
        "auth/kubernetes/role/cert-manager bound_service_account_names=cert-manager"
        " bound_service_account_namespaces=cert-manager"
    ) in setup
    assert "policies=argos-cert-issuer" in setup


def test_the_bootstrap_verifies_postgres_with_the_ca_of_the_bench() -> None:
    script = (ROOT / "platform" / "k8s" / "base" / "core" / "bootstrap" / "bootstrap.py").read_text(
        encoding="utf-8"
    )
    assert "sslmode=verify-full" in script and "sslrootcert=" in script
    # Vault 1.17 ignores `tls_ca`: it reads the CA from a file mounted in its pod.
    assert "sslrootcert=/run/postgres-ca/ca.crt" in script, "Vault verifies with the same CA"


ACCOUNTS_SH = ROOT / "platform" / "k8s" / "bench" / "accounts.sh"


def test_the_person_reads_the_accounts_on_the_vm_and_nothing_writes_them() -> None:
    script = ACCOUNTS_SH.read_text(encoding="utf-8")
    assert "get secret bench-accounts" in script
    assert ">" not in script.split("get secret", 1)[1].split("\n", 1)[0], "shown, never written"
    assert "tee" not in script


def test_an_account_is_reset_with_a_one_off_job_that_names_only_the_account() -> None:
    script = ACCOUNTS_SH.read_text(encoding="utf-8")
    assert "reset" in script and "RESET_USERS" in script
    assert "keycloak-accounts-reset" in script, "its own Job: the managed one is never touched"
    assert "delete job keycloak-accounts " not in script


def test_the_tunnel_takes_only_port_443_and_only_for_this_computer() -> None:
    """K-08: while 80 and 443 stay closed, the bench is tested through SSH on its final names."""
    script = (ROOT / "platform" / "k8s" / "bench" / "tunnel.sh").read_text(encoding="utf-8")
    [command] = [line for line in script.splitlines() if line.startswith("exec ssh")]
    assert "-L 127.0.0.1:443:127.0.0.1:443" in command, "listens only on this computer"
    assert command.count(" -L ") == 1 and " -R " not in command and " -D " not in command
    assert "127.0.0.1 api.34-134-21-66.sslip.io" in script
    assert "127.0.0.1 id.34-134-21-66.sslip.io" in script


def test_kyverno_is_installed_pinned_verified_and_before_the_bench() -> None:
    """K-09 (ADR-0014): the bench applies argos-pod-baseline; its kinds must exist first."""
    assert re.fullmatch(r"v\d+\.\d+\.\d+", _pinned("KYVERNO_VERSION"))
    assert re.fullmatch(r"[0-9a-f]{64}", _pinned("KYVERNO_SHA256"))
    script = _script()
    # Its CRDs do not fit in the annotation of a client-side apply.
    assert re.search(r"kubectl apply --server-side[^\n]*kyverno", script)
    assert script.index("== kyverno") < script.index("== flux controllers and the bench source")


def test_the_security_profiles_are_on_the_node_before_a_pod_asks_for_them() -> None:
    """K-09: a pod that names a Localhost profile missing on the node does not start."""
    script = _script()
    assert "/var/lib/kubelet/seccomp/argos" in script
    assert "platform/k8s/security/seccomp" in script
    assert "apparmor_parser -r" in script and "platform/k8s/security/apparmor" in script
    assert script.index("== security profiles") < script.index(
        "== flux controllers and the bench source"
    )
