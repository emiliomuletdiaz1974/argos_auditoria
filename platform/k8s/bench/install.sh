#!/usr/bin/env bash
# K-02F (DP-21) · one-time installation of the bench VM: k3s and Flux, pinned and verified.
#
# A person runs this once, on the VM, from a clone of the repository:
#
#   sudo apt-get install -y git && git clone https://github.com/emiliomuletdiaz1974/argos_auditoria.git
#   cd argos_auditoria && bash platform/k8s/bench/install.sh --dry-run   # what it would do
#   bash platform/k8s/bench/install.sh
#
# Every download is checked against the SHA-256 written below before it runs, and nothing is piped
# into a shell. Running it again changes nothing that is already in place. After it, the bench is
# deployed only from a tag banco-vX.Y.Z: Flux pulls the manifests that the workflow bench.yml
# signed, and refuses anything else. Synthetic data only (DP-20).
set -euo pipefail

K3S_VERSION="v1.36.5+k3s1"
K3S_INSTALLER_SHA256="46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad"
FLUX_VERSION="2.9.6"
FLUX_SHA256="b4d22673e9246cbd628881f1a9ef3b090085dced291e42d804555cee8e8d42c5"
CERT_MANAGER_VERSION="v1.21.2"
CERT_MANAGER_SHA256="e03b668ec8675214af6b0a671699d088f2601fa3878e0dbe1b41d3feafd1879f"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
KUBECONFIG_FILE="/etc/rancher/k3s/k3s.yaml"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

run() {
  echo "+ $*"
  if [[ "$DRY_RUN" == 0 ]]; then "$@"; fi
}

as_root() {
  if [[ "$(id -u)" == 0 ]]; then run "$@"; else run sudo "$@"; fi
}

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

echo "== k3s $K3S_VERSION"
if command -v k3s >/dev/null && k3s --version | grep -qF "$K3S_VERSION"; then
  echo "already installed"
else
  installer="$workdir/k3s-install.sh"
  run curl -fsSL -o "$installer" "https://raw.githubusercontent.com/k3s-io/k3s/${K3S_VERSION/+/%2B}/install.sh"
  if [[ "$DRY_RUN" == 0 ]]; then echo "$K3S_INSTALLER_SHA256  $installer" | sha256sum -c -; fi
  # The installer checks the k3s binary against the checksums of the same release. The secrets of
  # the cluster are encrypted at rest, and only root reads the kubeconfig.
  as_root env INSTALL_K3S_VERSION="$K3S_VERSION" sh "$installer" \
    --secrets-encryption --write-kubeconfig-mode 600
fi

echo "== flux $FLUX_VERSION"
if command -v flux >/dev/null && flux version --client | grep -qF "$FLUX_VERSION"; then
  echo "already installed"
else
  tarball="$workdir/flux.tar.gz"
  run curl -fsSL -o "$tarball" "https://github.com/fluxcd/flux2/releases/download/v${FLUX_VERSION}/flux_${FLUX_VERSION}_linux_amd64.tar.gz"
  if [[ "$DRY_RUN" == 0 ]]; then echo "$FLUX_SHA256  $tarball" | sha256sum -c -; fi
  run tar -xzf "$tarball" -C "$workdir" flux
  as_root install -m 0755 "$workdir/flux" /usr/local/bin/flux
fi

# cert-manager before the bench: the bench declares certificates, and their kinds must exist.
echo "== cert-manager $CERT_MANAGER_VERSION"
manifest="$workdir/cert-manager.yaml"
run curl -fsSL -o "$manifest" "https://github.com/cert-manager/cert-manager/releases/download/${CERT_MANAGER_VERSION}/cert-manager.yaml"
if [[ "$DRY_RUN" == 0 ]]; then echo "$CERT_MANAGER_SHA256  $manifest" | sha256sum -c -; fi
as_root env KUBECONFIG="$KUBECONFIG_FILE" k3s kubectl apply -f "$manifest"
as_root env KUBECONFIG="$KUBECONFIG_FILE" k3s kubectl -n cert-manager rollout status deploy/cert-manager-webhook --timeout=300s

echo "== flux controllers and the bench source"
as_root env KUBECONFIG="$KUBECONFIG_FILE" flux install --version="v$FLUX_VERSION"
as_root env KUBECONFIG="$KUBECONFIG_FILE" k3s kubectl apply -k "$REPO/platform/k8s/flux"

echo "== done: push a tag banco-vX.Y.Z and Flux deploys it once the workflow bench has signed it"
