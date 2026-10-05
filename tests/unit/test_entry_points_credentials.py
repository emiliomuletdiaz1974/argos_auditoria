"""F09-05 / K-07 · every process deployed with a dynamic database credential asks for it at start.

A Deployment of the bench that sets ARGOS_DATABASE_VAULT_ROLE runs a module; that module has to call
`start_from_config` before it connects, or it would connect with no user at all. The list comes
from the manifests, so a new service cannot be deployed without it. The inventory processes were
the gap: nothing deployed them until the bench (K-07).
"""

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "platform" / "k8s" / "base" / "services"


def _deployed_modules() -> dict[str, str]:
    found = {}
    for path in sorted(SERVICES.rglob("*.yaml")):
        for document in yaml.safe_load_all(path.read_text("utf-8")):
            if not isinstance(document, dict) or document.get("kind") != "Deployment":
                continue
            [container] = document["spec"]["template"]["spec"]["containers"]
            names = {e["name"] for e in container.get("env", [])}
            if "ARGOS_DATABASE_VAULT_ROLE" in names:
                found[document["metadata"]["name"]] = container["command"][-1]
    return found


def test_the_inventory_processes_are_deployed_with_a_credential() -> None:
    modules = _deployed_modules()
    assert modules["inventory-scheduler"] == "argos_inventory.scheduler.worker"
    assert modules["inventory-ingest"] == "argos_inventory.ingest.main"


def test_every_deployed_process_asks_for_its_credential_at_start() -> None:
    for deployment, module in _deployed_modules().items():
        spec = importlib.util.find_spec(module)
        assert spec is not None and spec.origin is not None, module
        source = Path(spec.origin).read_text(encoding="utf-8")
        assert "start_from_config(" in source, f"{deployment}: {module} never asks for it"
