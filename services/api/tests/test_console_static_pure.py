"""ARG-073 · the appliance serves the console from the same container as the API (ADR-0013).

One origin: the console is static files next to the v1, never a CDN. Any path that is not the API
answers the single page, because the console routes on the client; what does not exist under the
API is a 404 of the API, in problem+json, and never the page.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from argos_api import API_PREFIX
from argos_api.app import create_app


@pytest.fixture
def console(tmp_path: Path) -> Path:
    built = tmp_path / "console"
    (built / "assets").mkdir(parents=True)
    (built / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    (built / "assets" / "index.js").write_text("console.log(1)", encoding="utf-8")
    return built


def test_without_the_built_console_the_api_still_answers(tmp_path: Path) -> None:
    api = TestClient(create_app(None, console=tmp_path / "not-built"))
    assert api.get("/health").status_code == 200
    assert api.get("/").status_code == 404


def test_the_page_and_its_assets_come_from_the_same_origin(console: Path) -> None:
    api = TestClient(create_app(None, console=console))
    page = api.get("/")
    assert page.status_code == 200
    assert "id='root'" in page.text
    assert api.get("/assets/index.js").status_code == 200


def test_a_console_route_answers_the_page_so_a_reload_works(console: Path) -> None:
    api = TestClient(create_app(None, console=console))
    for route in ("/campaigns", "/findings/0192c000-0000-7000-8000-000000000001", "/evidence"):
        answer = api.get(route)
        assert answer.status_code == 200, route
        assert "id='root'" in answer.text


def test_an_unknown_api_route_is_a_problem_not_the_page(console: Path) -> None:
    api = TestClient(create_app(None, console=console))
    answer = api.get(f"{API_PREFIX}/nothing-here")
    assert answer.status_code == 404
    assert answer.headers["content-type"].startswith("application/problem+json")
