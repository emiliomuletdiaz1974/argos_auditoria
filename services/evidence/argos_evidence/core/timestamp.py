"""Verification of RFC 3161 time stamp replies (ARG-065).

Part of the pure verification core: no database, no store, no network.
"""

from __future__ import annotations

from cryptography import x509
from rfc3161_client import TimeStampResponse, VerifierBuilder, decode_timestamp_response
from rfc3161_client.errors import VerificationError

from argos_common.errors import ArgosError


class TimestampRejectedError(ArgosError):
    """A reply that does not stamp this object, for this request, from a trusted TSA."""


def verify_reply(
    reply: bytes, data: bytes, nonce: int | None, roots: list[x509.Certificate]
) -> TimeStampResponse:
    """The one verifier of every reply, online, imported or checked by a third party.

    ``nonce`` is the one of the request this reply answers; a third party that never saw the
    request passes ``None`` and the rest is still checked.
    """
    try:
        response = decode_timestamp_response(reply)
    except ValueError as exc:
        raise TimestampRejectedError(f"not a time stamp reply: {exc}") from exc
    try:
        VerifierBuilder(roots=list(roots), nonce=nonce).build().verify_message(response, data)
    except VerificationError as exc:
        raise TimestampRejectedError(str(exc)) from exc
    return response
