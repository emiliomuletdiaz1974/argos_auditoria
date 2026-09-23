"""Where a webhook may point: outside the appliance, over TLS (security review F09-02, SEC-031).

A webhook is a request the appliance makes to an address someone typed. Without a check it is a
way into the appliance's own network: Vault, the database, the metadata of the host. So:

- only `https`;
- never an internal name of the appliance (`vault`, `postgres`…) nor `localhost`;
- the name is resolved, and every address must be public. Loopback, private, link-local,
  multicast and reserved addresses are refused;
- except what the configuration allows: the client's ITSM usually lives on its private network,
  and that exception is written down by whoever installs the appliance, not by whoever subscribes.

The check runs when subscribing and again before every delivery, because a name can start
resolving somewhere else after it was accepted. What remains between that last resolution and the
connection (a rebinding in between) is written down in the module documentation.
"""

import ipaddress
import socket
from collections.abc import Callable, Iterable, Sequence
from urllib.parse import urlsplit

# The names of the services of the appliance, as its network resolves them.
INTERNAL_NAMES = frozenset(
    {
        "localhost",
        "api",
        "ai-gateway",
        "challenge-worker",
        "evidence",
        "evidence-worker",
        "keycloak",
        "llm",
        "nats",
        "opa",
        "postgres",
        "temporal",
        "vault",
        "verifier",
        "worm",
    }
)

Resolver = Callable[[str], Sequence[str]]


class DestinationRefusedError(ValueError):
    """The webhook would point where the appliance does not send anything."""


def resolve_host(host: str) -> list[str]:
    """Every address the name resolves to (IPv4 and IPv6)."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DestinationRefusedError(f"the host {host!r} does not resolve") from exc
    return sorted({str(info[4][0]) for info in infos})


def _allowed(address: str, host: str, allowed: Iterable[str]) -> bool:
    ip = ipaddress.ip_address(address)
    for entry in allowed:
        entry = entry.strip()
        if not entry:
            continue
        if entry.lower() == host.lower():
            return True
        try:
            if ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def check_destination(
    url: str, *, resolve: Resolver = resolve_host, allowed: Iterable[str] = ()
) -> None:
    """Nothing if the appliance may deliver to `url`; `DestinationRefusedError` saying why."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise DestinationRefusedError("a webhook is delivered over https only")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise DestinationRefusedError("the webhook has no host")
    allowed = tuple(allowed)
    if host.lower() in INTERNAL_NAMES and not any(
        entry.strip().lower() == host.lower() for entry in allowed
    ):
        raise DestinationRefusedError(f"{host!r} is a service of the appliance")
    try:
        addresses: Sequence[str] = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = resolve(host)
    if not addresses:
        raise DestinationRefusedError(f"the host {host!r} does not resolve")
    for address in addresses:
        if ipaddress.ip_address(address).is_global or _allowed(address, host, allowed):
            continue
        raise DestinationRefusedError(
            f"{host!r} resolves to a private or reserved address, not allowed by configuration"
        )
