"""ARG-065 · the time stamp request and the single verifier of every reply."""

import hashlib

import pytest

from argos_evidence.tsa import TimestampRejectedError, new_request, verify_reply


def test_a_request_stamps_the_sha256_of_the_object_with_a_nonce_and_the_certificate() -> None:
    data = b'{"payload":"root"}'
    request = new_request(data)
    assert request.message_imprint.message == hashlib.sha256(data).digest()
    assert request.message_imprint.hash_algorithm.dotted_string == "2.16.840.1.101.3.4.2.1"
    assert request.nonce
    assert request.cert_req
    assert new_request(data).nonce != request.nonce


def test_a_reply_that_is_not_a_time_stamp_is_rejected() -> None:
    with pytest.raises(TimestampRejectedError, match="not a time stamp reply"):
        verify_reply(b"not asn.1", b"data", nonce=1, roots=[])
