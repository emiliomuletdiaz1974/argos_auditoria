"""Translation layer between the jurist's editorial template and the internal model (ADR-0006).

Jurists edit obligations with Spanish field names; the core only knows English keys. The mapping
is closed and one-to-one: an unknown or repeated field is an error, never silently dropped.
"""

from collections.abc import Mapping
from typing import Any

import yaml

EDITORIAL_KEYS: Mapping[str, str] = {
    "id": "id",
    "norma": "norm",
    "articulo": "article",
    "titulo": "title",
    "vigente_desde": "in_force_from",
    "severidad": "severity",
    "texto_resumen": "summary",
    "aplica_a": "applies_to",
    "verificado_por": "verified_by",
    "equivalencias": "equivalences",
    "pendiente_verificacion": "verification_pending",
}
INTERNAL_KEYS: Mapping[str, str] = {internal: key for key, internal in EDITORIAL_KEYS.items()}


class _StrictLoader(yaml.SafeLoader):
    """A safe loader that refuses repeated keys instead of keeping the last one."""


def _mapping_without_duplicates(loader: _StrictLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise ValueError(f"duplicate editorial field: {key!r}")
        seen.add(key)
    return dict(loader.construct_mapping(node))


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_without_duplicates
)


def read_editorial(text: str) -> dict[str, Any]:
    document = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    if not isinstance(document, dict):
        raise ValueError("an editorial template must be a mapping of fields")
    return document


def to_internal(document: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(str(k) for k in document if k not in EDITORIAL_KEYS)
    if unknown:
        raise ValueError(f"unknown editorial fields: {unknown}")
    return {EDITORIAL_KEYS[key]: value for key, value in document.items()}


def to_editorial(document: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(str(k) for k in document if k not in INTERNAL_KEYS)
    if unknown:
        raise ValueError(f"unknown internal fields: {unknown}")
    return {INTERNAL_KEYS[key]: value for key, value in document.items()}
