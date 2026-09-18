"""Encrypted transport to the client's systems, unless the system is declared otherwise.

Credentials and samples cross the network before anything is hashed, so a connector refuses a
clear transport at `open()`. A system that genuinely has none (a loopback source in development, a
legacy share on an isolated segment) says so in its configuration with `allow_insecure: true`, and
that declaration lives in `argos.systems`, where an auditor reads it.
"""

from collections.abc import Mapping
from typing import Any

from argos_common.errors import ConfigurationError


def require_tls(encrypted: bool, config: Mapping[str, Any], target: str) -> None:
    if encrypted or config.get("allow_insecure") is True:
        return
    raise ConfigurationError(
        "the transport to the system is not encrypted; declare allow_insecure: true to accept it",
        details={"target": target},
    )
