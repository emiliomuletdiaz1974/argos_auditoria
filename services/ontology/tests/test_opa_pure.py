"""ARG-036 · the OPA client asks one package for its verdict and fails loudly otherwise."""

import json

import httpx
import pytest

from argos_ontology.opa import OpaError, evaluate

BASE = "http://opa.test:8181"


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_the_token_travels_as_a_bearer_and_only_when_there_is_one() -> None:
    # OPA decides verdicts: with authentication on, an anonymous call is refused.
    headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"result": {"compliant": True}})

    with _client(httpx.MockTransport(handler)) as client:
        evaluate("argos.retention", {}, BASE, client=client, token="dev-only-token")
        evaluate("argos.retention", {}, BASE, client=client)
    assert headers == ["Bearer dev-only-token", None]


def test_a_refused_token_is_reported_as_such() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "unauthorized"})

    with _client(httpx.MockTransport(handler)) as client, pytest.raises(OpaError, match="401"):
        evaluate("argos.retention", {}, BASE, client=client, token="wrong")


def test_posts_the_input_to_the_verdict_of_the_package_and_returns_it() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"result": {"compliant": True, "rule": "argos.retention"}})

    with _client(httpx.MockTransport(handler)) as client:
        verdict = evaluate("argos.retention", {"max_age_days": 10}, BASE, client=client)
    assert verdict == {"compliant": True, "rule": "argos.retention"}
    assert str(seen[0].url) == f"{BASE}/v1/data/argos/retention/verdict"
    assert json.loads(seen[0].content) == {"input": {"max_age_days": 10}}


@pytest.mark.parametrize(
    "package",
    ["retention", "argos", "argos.", "argos.Retention", "argos.retention/../x", "other.retention"],
)
def test_package_names_outside_the_argos_namespace_are_refused_before_any_call(
    package: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with (
        _client(httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match="package"),
    ):
        evaluate(package, {}, BASE, client=client)


def test_a_package_without_verdict_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with _client(httpx.MockTransport(handler)) as client, pytest.raises(OpaError, match="verdict"):
        evaluate("argos.unknown", {}, BASE, client=client)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(200, json={"result": ["not", "an", "object"]}),
    ],
)
def test_server_errors_and_malformed_verdicts_are_errors(response: httpx.Response) -> None:
    with (
        _client(httpx.MockTransport(lambda request: response)) as client,
        pytest.raises(OpaError),
    ):
        evaluate("argos.access", {}, BASE, client=client)


def test_an_unreachable_server_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with _client(httpx.MockTransport(handler)) as client, pytest.raises(OpaError, match="reach"):
        evaluate("argos.access", {}, BASE, client=client)
