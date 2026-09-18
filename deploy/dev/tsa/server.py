"""RFC 3161 over HTTP for the development environment: POST a query, get a reply.

GET /ca.pem gives the test root so clients can build their trust store, and
GET /health answers 200. Replies are produced by `openssl ts -reply`, one at a
time because the serial file is shared.
"""

import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG = "/tsa/openssl.cnf"
OPENSSL = "/usr/bin/openssl"
CA = Path("/data/ca.pem")
MAX_QUERY = 16 * 1024
_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, b"ok", "text/plain")
        elif self.path == "/ca.pem":
            self._send(200, CA.read_bytes(), "application/x-pem-file")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if self.headers.get("Content-Type") != "application/timestamp-query":
            self._send(415, b"expected application/timestamp-query", "text/plain")
            return
        if not 0 < length <= MAX_QUERY:
            self._send(413, b"query too large", "text/plain")
            return
        query = self.rfile.read(length)
        with tempfile.TemporaryDirectory() as work, _LOCK:
            query_file, reply_file = Path(work, "q.tsq"), Path(work, "r.tsr")
            query_file.write_bytes(query)
            # Fixed arguments; the client query only ever reaches openssl as a file.
            done = subprocess.run(  # noqa: S603
                [
                    OPENSSL,
                    "ts",
                    "-reply",
                    "-config",
                    CONFIG,
                    "-queryfile",
                    str(query_file),
                    "-out",
                    str(reply_file),
                ],
                capture_output=True,
                check=False,
            )
            if done.returncode != 0 or not reply_file.exists():
                self._send(400, b"bad query", "text/plain")
                return
            reply = reply_file.read_bytes()
        self._send(200, reply, "application/timestamp-reply")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 3180), Handler).serve_forever()  # noqa: S104 - container port
