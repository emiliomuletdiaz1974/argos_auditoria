"""Transport to a client system is encrypted unless the system is declared otherwise."""

import pytest

from argos_common.errors import ConfigurationError
from argos_connector.tls import require_tls


def test_an_encrypted_transport_needs_nothing_declared() -> None:
    require_tls(True, {}, "https://api.hospital.test")


def test_a_clear_transport_is_refused_by_default() -> None:
    with pytest.raises(ConfigurationError, match="allow_insecure"):
        require_tls(False, {}, "http://api.hospital.test")


@pytest.mark.parametrize("flag", ["true", 1, "yes"])
def test_only_a_literal_true_allows_a_clear_transport(flag: object) -> None:
    # A truthy string in a hand-edited catalogue is not a decision.
    with pytest.raises(ConfigurationError):
        require_tls(False, {"allow_insecure": flag}, "http://api.hospital.test")


def test_a_declared_clear_transport_is_allowed() -> None:
    require_tls(False, {"allow_insecure": True}, "http://127.0.0.1:8090")
