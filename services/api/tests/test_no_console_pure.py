"""The API serves no page: the front end is its own application, on its own origin (ARG-073).

The console of phase 08 stays in `console/` as code, but the API image neither builds it nor
mounts it. What is not a route of the API is a 404 of the API, in problem+json, with the same
security headers as every other answer.
"""

import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def test_the_application_takes_no_console_to_serve() -> None:
    assert "console" not in inspect.signature(create_app).parameters


def test_a_path_outside_the_api_is_a_problem_not_a_page() -> None:
    api = TestClient(create_app(None))
    finding = "/findings/0192c000-0000-7000-8000-000000000001"
    for path in ("/", "/campaigns", finding, "/assets/x.js"):
        answer = api.get(path)
        assert answer.status_code == 404, path
        assert answer.headers["content-type"].startswith("application/problem+json"), path


def test_the_api_still_answers_without_a_console() -> None:
    api = TestClient(create_app(None))
    assert api.get("/health").status_code == 200
    assert api.get(f"{API_PREFIX}/nothing-here").status_code == 404


def test_the_image_builds_no_front_end() -> None:
    recipe = DOCKERFILE.read_text(encoding="utf-8")
    assert "node" not in recipe and "npm" not in recipe, "the API image carries no console"
