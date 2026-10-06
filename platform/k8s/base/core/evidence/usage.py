"""K-99 · publishes, inside the cluster, how full the volume of the WORM store is.

Used and total bytes of the filesystem of /data, and nothing about what the store keeps. The health
service reads it (ARG-094, the alert EvidenceDisk85): in development it mounts the volume read-only,
and in the bench the volume belongs to this StatefulSet, in another namespace. Only the standard
library; it listens on 9101, which only the health service reaches.
"""

import json
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer

DATA = "/data"
PORT = 9101


class Usage(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - the name http.server calls
        if self.path != "/usage":
            self.send_error(404)
            return
        usage = shutil.disk_usage(DATA)
        body = json.dumps({"used": usage.used, "total": usage.total}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - its signature
        """Quiet: a request every half minute is not news."""


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Usage).serve_forever()  # noqa: S104 - the pod's own address
