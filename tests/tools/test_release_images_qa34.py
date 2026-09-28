"""Quality review QA-01, QA-082 · every image that runs is built, has its SBOM and is updated.

`argos-health` ran in the environment but was left out of the build, the SBOM, the vulnerability
gate and the updater: a release could not carry it and an update could not change it. The four
lists are compared with what the compose file runs.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import yaml

from argos_updater.cli import SERVICES

REPO = Path(__file__).resolve().parents[2]


def _tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _running() -> set[str]:
    compose = yaml.safe_load((REPO / "deploy" / "dev" / "compose.yaml").read_text("utf-8"))
    images = {str(s.get("image", "")) for s in compose["services"].values()}
    # `argos-dev/…` are the simulated sources and services of the environment, not the product.
    product = {i for i in images if i.startswith("argos-") and "/" not in i}
    return {i.split(":", 1)[0] for i in product if i.endswith(":dev")}


def _built() -> set[str]:
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    return set(re.findall(r"-t (argos-[a-z-]+):\$\(VERSION\)", makefile))


def test_every_image_that_runs_is_built_listed_in_the_sbom_and_updated() -> None:
    running = _running()
    assert "argos-health" in running
    assert running <= _built(), running - _built()
    assert running <= set(_tool("sbom").IMAGES), running - set(_tool("sbom").IMAGES)
    assert running <= set(SERVICES), running - set(SERVICES)
