"""K-02 · what the CI publishes for the bench: every image pinned by its digest in GHCR (DP-21).

The tag `banco-vX.Y.Z` is the only way to deploy the bench. The CI turns it into the version of
the artifact, and writes a kustomization over the `bench-gcp` overlay that replaces each image of
ARGOS by the one it just built and signed, by digest: a tag that moves is never deployed.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "bench_render.py"
DIGEST = "sha256:" + "a" * 64


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bench_render", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bench_render = _tool()


@pytest.mark.parametrize(
    ("tag", "version"), [("banco-v0.1.0", "0.1.0"), ("banco-v12.3.40", "12.3.40")]
)
def test_the_version_comes_from_the_bench_tag(tag: str, version: str) -> None:
    assert bench_render.version_of(tag) == version


@pytest.mark.parametrize(
    "tag", ["v0.1.0", "banco-v0.1", "banco-v0.1.0-rc1", "banco-v0.1.0;rm -rf /", "fase-10", ""]
)
def test_any_other_tag_is_refused(tag: str) -> None:
    with pytest.raises(ValueError, match="banco-v"):
        bench_render.version_of(tag)


def test_the_images_are_the_ones_make_build_builds() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    built = dict(re.findall(r"docker build -f (\S+)/Dockerfile .*? -t (argos-[a-z-]+):", makefile))
    assert {name: f"{folder}/Dockerfile" for folder, name in built.items()} == {
        name: image.dockerfile for name, image in bench_render.IMAGES.items()
    }


def test_each_image_is_replaced_by_its_digest_in_ghcr(tmp_path: Path) -> None:
    digests = dict.fromkeys(bench_render.ALL_IMAGES, DIGEST)
    kustomization = bench_render.render(digests, owner="Emilio-Org", out=tmp_path / "rendered")
    assert len(kustomization["resources"]) == 1, "only the bench overlay"
    images = {entry["name"]: entry for entry in kustomization["images"]}
    assert set(images) == set(bench_render.ALL_IMAGES)
    for name, entry in images.items():
        assert entry == {"name": name, "newName": f"ghcr.io/emilio-org/{name}", "digest": DIGEST}
    written = yaml.safe_load((tmp_path / "rendered" / "kustomization.yaml").read_text("utf-8"))
    assert written == kustomization


def test_the_overlay_is_reachable_from_where_it_is_rendered(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    bench_render.render(dict.fromkeys(bench_render.ALL_IMAGES, DIGEST), owner="o", out=out)
    resource = yaml.safe_load((out / "kustomization.yaml").read_text("utf-8"))["resources"][0]
    assert (out / resource / "kustomization.yaml").resolve() == (
        bench_render.OVERLAY / "kustomization.yaml"
    ).resolve()


@pytest.mark.parametrize("digest", ["sha256:short", "latest", "sha512:" + "a" * 128, ""])
def test_a_digest_that_is_not_one_is_refused(tmp_path: Path, digest: str) -> None:
    digests = dict.fromkeys(bench_render.ALL_IMAGES, DIGEST) | {"argos-api": digest}
    with pytest.raises(ValueError, match="argos-api"):
        bench_render.render(digests, owner="o", out=tmp_path / "rendered")


def test_an_image_without_digest_is_refused(tmp_path: Path) -> None:
    digests = dict.fromkeys(bench_render.ALL_IMAGES, DIGEST)
    del digests["argos-api"]
    with pytest.raises(ValueError, match="argos-api"):
        bench_render.render(digests, owner="o", out=tmp_path / "rendered")


def test_the_cli_reads_one_digest_file_per_image(tmp_path: Path) -> None:
    folder = tmp_path / "digests"
    folder.mkdir()
    for name in bench_render.ALL_IMAGES:
        (folder / name).write_text(DIGEST + "\n", encoding="utf-8")
    out = tmp_path / "rendered"
    assert (
        bench_render.main(["render", "--digests", str(folder), "--owner", "o", "--out", str(out)])
        == 0
    )
    assert (out / "kustomization.yaml").is_file()


def test_the_images_of_the_bench_are_built_from_their_own_context() -> None:
    """PostgreSQL with AGE and pgvector is not a service of ARGOS, but the bench builds it too."""
    assert "argos-postgres" in bench_render.BENCH_IMAGES
    for name, image in bench_render.ALL_IMAGES.items():
        assert (ROOT / image.dockerfile).is_file(), name
        assert (ROOT / image.dockerfile).resolve().is_relative_to((ROOT / image.context).resolve())


def test_every_built_image_is_pinned_when_rendered(tmp_path: Path) -> None:
    digests = dict.fromkeys(bench_render.ALL_IMAGES, DIGEST)
    kustomization = bench_render.render(digests, owner="o", out=tmp_path / "rendered")
    assert {entry["name"] for entry in kustomization["images"]} == set(bench_render.ALL_IMAGES)


def test_opa_is_built_with_its_policies_from_the_root_of_the_repository() -> None:
    opa = bench_render.BENCH_IMAGES["argos-opa"]
    assert opa.context == "." and opa.dockerfile == "platform/k8s/images/opa/Dockerfile"


def test_the_test_tsa_is_built_from_its_own_folder() -> None:
    tsa = bench_render.BENCH_IMAGES["argos-tsa"]
    assert tsa.context == "deploy/dev/tsa" and tsa.dockerfile == "deploy/dev/tsa/Dockerfile"
