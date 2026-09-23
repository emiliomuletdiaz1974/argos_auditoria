"""Declarative REST connector: safe methods only, routes matched exactly (ARG-019)."""

import re
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Self
from urllib.parse import urlencode

import httpx

from argos_common.errors import ReadOnlyViolationError
from argos_connector.base import Connector
from argos_connector.probes import ProbeSpec
from argos_connector.readonly import assert_safe_http_method
from argos_connector.tls import require_tls

SECURITY_HEADERS = (
    "strict-transport-security",
    "x-content-type-options",
    "cache-control",
    "server",
)
DEFAULT_MAX_PAGES = 100
_PARAMETER = re.compile(r"^\{[A-Za-z_][A-Za-z0-9_]*\}$")
_LITERAL = re.compile(r"^[A-Za-z0-9._~$:@!,;=+-]+$")


def dig(data: Any, dotted: str | None) -> Any:
    if dotted is None:
        return None
    current = data
    for part in dotted.split("."):
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


@dataclass(frozen=True, slots=True)
class Route:
    template: str
    pattern: re.Pattern[str]
    items_field: str | None = None
    count_field: str | None = None
    page_param: str | None = None
    next_field: str | None = None
    defaults: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_descriptor(cls, raw: Mapping[str, Any]) -> Self:
        template = str(raw["path"])
        if not template.startswith("/"):
            raise ValueError(f"invalid route template: {template!r}")
        pieces = []
        for segment in template.strip("/").split("/"):
            if segment == "" and template == "/":
                pieces.append("")
            elif _PARAMETER.match(segment):
                pieces.append("[^/]+")
            elif _LITERAL.match(segment) and segment not in (".", ".."):
                pieces.append(re.escape(segment))
            else:
                raise ValueError(f"invalid route template: {template!r}")
        page = raw.get("page") or {}
        return cls(
            template=template,
            pattern=re.compile("^/" + "/".join(pieces) + "$"),
            items_field=raw.get("items_field"),
            count_field=raw.get("count_field"),
            page_param=page.get("param"),
            next_field=page.get("next_field"),
            defaults=dict(raw.get("defaults", {})),
        )

    def concrete(self) -> str:
        return self.template.format(**self.defaults) if self.defaults else self.template


class RestConnector(Connector):
    kind = "api"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client: httpx.Client | None = None
        self._base: httpx.URL | None = None
        self._routes: tuple[Route, ...] = ()

    # ---------- lifecycle ----------
    def _descriptor(self) -> Mapping[str, Any]:
        descriptor: Mapping[str, Any] = self.config["descriptor"]
        return descriptor

    def _client_options(self) -> dict[str, Any]:
        return {}

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._base is None:
            raise RuntimeError("connector is not open: call open() first")
        return self._client

    @property
    def base(self) -> httpx.URL:
        if self._base is None:
            raise RuntimeError("connector is not open: call open() first")
        return self._base

    def open(self) -> None:
        descriptor = self._descriptor()
        raw_base = descriptor.get("base_url") or self.context.credentials["base_url"]
        base_url = str(raw_base).rstrip("/")
        require_tls(httpx.URL(base_url).scheme == "https", self.config, base_url)
        routes = tuple(Route.from_descriptor(r) for r in descriptor["routes"])
        headers = {"Accept": "application/json"}
        token = self.context.credentials.get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        verify: ssl.SSLContext | bool = True
        if self.config.get("ca_file"):
            verify = ssl.create_default_context(cafile=str(self.config["ca_file"]))
        self._client = httpx.Client(
            base_url=base_url,
            headers=headers,
            verify=verify,
            timeout=float(self.config.get("timeout_s", 15.0)),
            follow_redirects=False,
            **self._client_options(),
        )
        self._base, self._routes = httpx.URL(base_url), routes

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---------- allowlist ----------
    def route_for(self, path: str) -> Route:
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            raise ReadOnlyViolationError(f"path must be relative to the API base: {path!r}")
        lowered = path.lower()
        if ".." in path or "\\" in path or any(c in lowered for c in ("%2e", "%2f", "%5c")):
            raise ReadOnlyViolationError(f"suspicious path: {path!r}")
        path_only = path.split("?", 1)[0]
        for route in self._routes:
            if route.pattern.match(path_only):
                return route
        raise ReadOnlyViolationError(f"path outside the allowlist: {path_only!r}")

    def _request(
        self, method: str, path: str, params: Mapping[str, Any] | None = None
    ) -> httpx.Response:
        verb = assert_safe_http_method(method)
        self.route_for(path)
        # An empty params mapping would replace the query of a revalidated pagination link.
        return self.client.request(verb, path, params=dict(params) if params else None)

    def _json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        response = self._request("GET", path, params)
        response.raise_for_status()
        return response.json()

    def _next_path(self, link: Any) -> str:
        base = self.base
        url = base.join(str(link))
        if (url.scheme, url.host, url.port) != (base.scheme, base.host, base.port):
            raise ReadOnlyViolationError("pagination link points to another origin")
        base_path = base.path.rstrip("/")
        if base_path and not (url.path == base_path or url.path.startswith(base_path + "/")):
            raise ReadOnlyViolationError("pagination link leaves the API base path")
        relative = url.path[len(base_path) :] or "/"
        query = url.query.decode("ascii")
        return f"{relative}?{query}" if query else relative

    # ---------- rendering ----------
    def render(self, spec: ProbeSpec) -> ProbeSpec:
        if spec.kind == "scan_schema":
            lines = []
            for route in self._routes:
                concrete = route.concrete()
                self.route_for(concrete)
                lines.append(f"HEAD {concrete}")
            return replace(spec, statement="\n".join(lines))
        if spec.kind not in ("count", "sample", "check_config"):
            return spec
        self.route_for(spec.target)
        query = dict(spec.params.get("query", {}))
        encoded = f"?{urlencode(sorted(query.items()))}" if query else ""
        return replace(spec, statement=f"GET {spec.target}{encoded}")

    # ---------- probes ----------
    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        found = []
        for route in self._routes:
            response = self._request("HEAD", route.concrete())
            found.append(
                {
                    "path": route.template,
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                }
            )
        return {"routes": found}, len(found)

    def _do_count(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        route = self.route_for(spec.target)
        query = dict(spec.params.get("query", {}))
        if route.count_field:
            total = int(dig(self._json(spec.target, query), route.count_field))
            return {"count": total, "capped": False, "pages": 1}, total
        if not route.items_field:
            raise ValueError(f"route {route.template} declares neither count_field nor items_field")
        cap = min(int(spec.params.get("cap", 100_000)), 1_000_000)
        # The probe took one permit from the load budget; its pages must not be unlimited.
        max_pages = int(self.config.get("max_pages", DEFAULT_MAX_PAGES))
        counted, pages = 0, 0
        path, params = spec.target, query
        while counted < cap:
            if pages >= max_pages:
                return {"count": counted, "capped": True, "pages": pages}, counted
            if pages == 0:
                body = self._json(path, params)
            else:  # the server chose this page: it is journaled and paid for (SEC-023)
                with self.follow_up(
                    ProbeSpec("count", path, params={"query": params, "page": pages + 1})
                ):
                    body = self._json(path, params)
            items = dig(body, route.items_field) or []
            counted += len(items)
            pages += 1
            following = dig(body, route.next_field)
            if not items or not following:
                break
            if route.page_param:
                path, params = spec.target, {**query, route.page_param: following}
            else:
                path, params = self._next_path(following), {}
        total = min(counted, cap)
        return {"count": total, "capped": counted >= cap, "pages": pages}, total

    def _do_sample(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        route = self.route_for(spec.target)
        fields = list(spec.params.get("fields") or [])
        if not fields:
            raise ValueError("sample needs at least one field")
        limit = min(int(spec.params.get("k", 50)), self.context.budget.max_rows_per_probe)
        body = self._json(spec.target, spec.params.get("query", {}))
        items = (dig(body, route.items_field) or [])[:limit]
        hasher = self.context.hasher
        rows = [{name: hasher.digest(dig(item, name)) for name in fields} for item in items]
        return {"n": len(rows), "fields": fields, "rows": rows}, len(rows)

    def _do_check_config(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        response = self._request("GET", spec.target)
        headers = {name: response.headers.get(name) for name in SECURITY_HEADERS}
        data = {
            "status": response.status_code,
            "security_headers": headers,
            "tls_version": _tls_version(response),
        }
        return data, 1


def _tls_version(response: httpx.Response) -> str | None:
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    ssl_object = stream.get_extra_info("ssl_object")
    return str(ssl_object.version()) if ssl_object is not None else None
