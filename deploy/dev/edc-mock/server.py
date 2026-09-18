"""Simulated EDC Management API (v3) for the development environment (ARG-070).

It implements only what ARGOS uses: creating assets, policy definitions and
contract definitions, and listing them. It checks the shape of each body the
way the real connector would reject it, requires the API key, keeps state in
memory and answers 409 to an id it already holds. The real connector comes with
F07-16.
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = os.environ["EDC_API_KEY"]
EDC_VOCAB = "https://w3id.org/edc/v0.0.1/ns/"
KINDS = ("assets", "policydefinitions", "contractdefinitions")
MAX_BODY = 1024 * 1024
_STATE: dict[str, dict[str, dict[str, object]]] = {kind: {} for kind in KINDS}
_LOCK = threading.Lock()


def _problem(kind: str, body: dict[str, object]) -> str | None:
    context = body.get("@context")
    if not isinstance(context, dict) or context.get("@vocab") != EDC_VOCAB:
        return "the @context must declare the EDC vocabulary"
    if not isinstance(body.get("@id"), str) or not body["@id"]:
        return "@id is required"
    if kind == "assets":
        address = body.get("dataAddress")
        if not isinstance(address, dict) or not address.get("type"):
            return "dataAddress.type is required"
        if not isinstance(body.get("properties"), dict):
            return "properties is required"
    if kind == "policydefinitions":
        policy = body.get("policy")
        if not isinstance(policy, dict) or policy.get("@type") not in ("Set", "Offer", "odrl:Set"):
            return "policy must be an ODRL Set or Offer"
    if kind == "contractdefinitions":
        for field in ("accessPolicyId", "contractPolicyId"):
            if body.get(field) not in _STATE["policydefinitions"]:
                return f"{field} does not name a known policy definition"
        if not isinstance(body.get("assetsSelector"), list):
            return "assetsSelector must be a list of criteria"
    return None


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: object) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.headers.get("x-api-key") != API_KEY:
            self._send(401, [{"message": "invalid api key"}])
            return
        parts = self.path.strip("/").split("/")
        if len(parts) < 3 or parts[0] != "management" or parts[1] != "v3" or parts[2] not in KINDS:
            self._send(404, [{"message": "unknown endpoint"}])
            return
        kind = parts[2]
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send(413, [{"message": "body too large"}])
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._send(400, [{"message": "the body is not JSON"}])
            return
        with _LOCK:
            if parts[3:] == ["request"]:
                self._send(200, list(_STATE[kind].values()))
                return
            problem = (
                _problem(kind, body) if isinstance(body, dict) else "the body is not an object"
            )
            if problem:
                self._send(400, [{"message": problem}])
                return
            if body["@id"] in _STATE[kind]:
                self._send(409, [{"message": f"{body['@id']} already exists"}])
                return
            _STATE[kind][body["@id"]] = body
        self._send(
            200, {"@type": "IdResponse", "@id": body["@id"], "createdAt": int(time.time() * 1000)}
        )

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 19193), Handler).serve_forever()  # noqa: S104 - container port
