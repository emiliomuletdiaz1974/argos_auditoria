"""How a delivery is signed, and how the receiver checks it (ARG-079).

The header is `X-Argos-Signature: t=<unix seconds>,v1=<hex>`, where `<hex>` is the HMAC-SHA256,
with the secret of the subscription, of the timestamp, a dot and the exact bytes of the body. The
receiver recomputes it, compares in constant time and refuses a timestamp older than five minutes:
the body proves it is ARGOS and that nothing changed; the time, that it is not a replay.
"""

import hashlib
import hmac

SIGNATURE_HEADER = "X-Argos-Signature"
EVENT_HEADER = "X-Argos-Event"
TOLERANCE_SECONDS = 300


def _mac(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return f"t={timestamp},v1={_mac(secret, str(timestamp), body)}"


def verify(
    secret: str, header: str, body: bytes, now: int, tolerance: int = TOLERANCE_SECONDS
) -> bool:
    """What a receiver does. Never an exception: a header that does not parse does not verify."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp, received = parts["t"], parts["v1"]
        moment = int(timestamp)
    except (KeyError, ValueError):
        return False
    if not received or abs(now - moment) > tolerance:
        return False
    return hmac.compare_digest(_mac(secret, timestamp, body), received)
