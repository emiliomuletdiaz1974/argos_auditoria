"""K-02 · the workflow that publishes the bench (DP-21): only on a bench tag, asking for no more
than it uses.

It builds the images of ARGOS, signs each one by digest and publishes the rendered manifests as a
signed OCI artifact, which Flux verifies on the VM before applying anything. It never writes to
the repository and never holds a credential of the VM.
"""

import importlib.util
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "bench.yml"
ALLOWED = {"contents": "read", "packages": "write", "id-token": "write"}


def _workflow() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data


def _on(workflow: dict[str, Any]) -> Any:
    # YAML 1.1 reads a bare `on` as True.
    return workflow.get("on", workflow.get(True))


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = job.get("steps", [])
    return steps


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in _steps(job))


def _images() -> set[str]:
    spec = importlib.util.spec_from_file_location(
        "bench_render", ROOT / "tools" / "bench_render.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.BUILT)


def test_it_runs_only_on_a_bench_tag() -> None:
    assert _on(_workflow()) == {"push": {"tags": ["banco-v*"]}}


def test_the_token_reads_by_default_and_each_job_asks_only_for_what_it_uses() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        permissions = job.get("permissions", {})
        assert set(permissions.items()) <= set(ALLOWED.items()), name
        assert permissions.get("contents", "read") == "read", f"{name} would write the repository"


def test_every_image_of_argos_is_built() -> None:
    [images_job] = [j for j in _workflow()["jobs"].values() if "matrix" in j.get("strategy", {})]
    entries = images_job["strategy"]["matrix"]["image"]
    assert {entry["name"] for entry in entries} == _images()
    assert all("context" in entry for entry in entries), "each image builds from its own context"


def test_each_image_is_signed_by_its_digest() -> None:
    [images_job] = [j for j in _workflow()["jobs"].values() if "matrix" in j.get("strategy", {})]
    runs = _runs(images_job)
    assert "cosign sign --yes" in runs
    assert "@${{ steps.build.outputs.digest }}" in runs, "signed by digest, never by a tag"


def test_the_manifests_are_published_as_a_signed_artifact() -> None:
    [publish] = [j for j in _workflow()["jobs"].values() if "flux push artifact" in _runs(j)]
    runs = _runs(publish)
    assert "tools/bench_render.py version" in runs, "the tag is checked before anything is built"
    assert "tools/bench_render.py render" in runs
    assert "flux push artifact" in runs
    assert runs.count("cosign sign --yes") == 1


def test_nothing_is_built_before_the_checks_pass() -> None:
    jobs = _workflow()["jobs"]
    [images_job] = [j for j in jobs.values() if "matrix" in j.get("strategy", {})]
    verify = jobs[images_job["needs"]]
    assert "make lint typecheck test" in _runs(verify)


def test_the_tag_is_checked_before_building() -> None:
    [images_job] = [j for j in _workflow()["jobs"].values() if "matrix" in j.get("strategy", {})]
    first_run = next(step["run"] for step in _steps(images_job) if "run" in step)
    assert "tools/bench_render.py version" in first_run


def test_one_image_that_fails_does_not_cancel_the_others() -> None:
    """K-99: a cut of PyPI while building one image cancelled the other twelve (banco-v0.12.1).
    Without fail-fast the others finish, and only the failed one is run again."""
    [images_job] = [j for j in _workflow()["jobs"].values() if "matrix" in j.get("strategy", {})]
    assert images_job["strategy"]["fail-fast"] is False


def test_an_image_whose_inputs_did_not_change_is_reused_not_built() -> None:
    """K-99: rebuilding PostgreSQL gave it a new digest on every tag, and the pod was recreated
    with each version: the services that started meanwhile found no database credential."""
    [images_job] = [j for j in _workflow()["jobs"].values() if "matrix" in j.get("strategy", {})]
    steps = {step.get("id") or step.get("name"): step for step in images_job["steps"]}
    assert "bench_render.py inputs" in steps["inputs"]["run"]
    assert "imagetools inspect" in steps["reuse"]["run"]
    assert steps["build"]["if"] == "steps.reuse.outputs.digest == ''"
    assert ":inputs-{2}" in steps["build"]["with"]["tags"], "tagged with its fingerprint"
    assert steps["sign the image by its digest"]["if"] == "steps.reuse.outputs.digest == ''"
    keep = steps["keep the digest for the manifests"]["run"]
    assert "steps.reuse.outputs.digest || steps.build.outputs.digest" in keep
