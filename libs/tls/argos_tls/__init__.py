"""ARG-083 · mutual TLS between ARGOS services, with certificates that change without a restart.

Every service has a folder with three files, written by the certificate issuer (`cert-issuer` in
the development environment, cert-manager on the appliance): its certificate, its private key and
the internal CA. Both sides of every link present a certificate and require one from the other,
signed by that CA; nothing below TLS 1.3 is spoken.

Certificates live 30 days and are renewed at 20, so a service must take the new one without a
restart:

* a **server** context keeps serving with its current certificate and, on every handshake, checks
  (at most every `check_interval` seconds) whether the files changed; if they did, that handshake
  and the next ones use a context built from the new files (`sni_callback` swaps it in);
* a **client** context is asked for per connection or per client (`context()`, `mtls_client()`),
  and is rebuilt when the files changed.
"""

import os
import ssl
import threading
import time
from pathlib import Path
from typing import Any

import httpx

CERT_FILE = "tls.crt"
KEY_FILE = "tls.key"
CA_FILE = "ca.crt"

__all__ = [
    "CA_FILE",
    "CERT_FILE",
    "KEY_FILE",
    "ReloadingTLS",
    "mtls_async_client",
    "mtls_client",
    "serve",
]


class ReloadingTLS:
    """The TLS context of one side of a link, rebuilt when its certificate changes on disk."""

    def __init__(self, server: bool, cert_dir: Path | str, check_interval: float = 5.0) -> None:
        self.server = server
        self.cert_dir = Path(cert_dir)
        self._interval = check_interval
        self._lock = threading.Lock()
        self._checked = 0.0
        self._stamp = self._files_stamp()
        self._current = self._build()
        self._base: ssl.SSLContext | None = None

    def _files_stamp(self) -> tuple[float, ...]:
        return tuple(
            os.stat(self.cert_dir / name).st_mtime for name in (CERT_FILE, KEY_FILE, CA_FILE)
        )

    def _build(self) -> ssl.SSLContext:
        purpose = ssl.PROTOCOL_TLS_SERVER if self.server else ssl.PROTOCOL_TLS_CLIENT
        context = ssl.SSLContext(purpose)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(self.cert_dir / CERT_FILE, self.cert_dir / KEY_FILE)
        context.load_verify_locations(cafile=self.cert_dir / CA_FILE)
        context.verify_mode = ssl.CERT_REQUIRED  # both roles: nobody talks without a certificate
        if not self.server:
            context.check_hostname = True
        return context

    def _fresh(self) -> ssl.SSLContext:
        now = time.monotonic()
        with self._lock:
            if now - self._checked < self._interval:
                return self._current
            self._checked = now
            try:
                stamp = self._files_stamp()
                if stamp != self._stamp:
                    self._current = self._build()
                    self._stamp = stamp
            except (OSError, ssl.SSLError):
                pass  # a certificate half written: keep the current one and look again later
            return self._current

    def _swap(self, sock: ssl.SSLObject | ssl.SSLSocket, _name: str | None, _: Any) -> None:
        sock.context = self._fresh()

    def context(self) -> ssl.SSLContext:
        """For a server, one context whose handshakes always use the latest certificate; for a
        client, the latest context itself."""
        if not self.server:
            return self._fresh()
        if self._base is None:
            base = self._build()
            base.sni_callback = self._swap
            self._base = base
        return self._base


def mtls_client(cert_dir: Path | str, **kwargs: Any) -> httpx.Client:
    """An HTTP client that presents the certificate of this service and verifies the other one."""
    return httpx.Client(verify=ReloadingTLS(False, cert_dir).context(), **kwargs)


def mtls_async_client(cert_dir: Path | str, **kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(verify=ReloadingTLS(False, cert_dir).context(), **kwargs)


def serve(app: Any, host: str, port: int, cert_dir: Path | str, **kwargs: Any) -> None:
    """Run an ASGI application with uvicorn, requiring a client certificate on every connection."""
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, **kwargs)
    config.load()
    config.ssl = ReloadingTLS(True, cert_dir).context()
    uvicorn.Server(config).run()
