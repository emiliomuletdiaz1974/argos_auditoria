"""Spanish layer of the challenge DSL (ADR-0007, decision of F05-00).

A challenge can be written with Spanish keys and enumerated values; this module translates it to the
English core with a closed, injective table before anything validates it, and back when a challenge
is handed over for editing. A key or a value outside the table is an error, never something ignored:
the core never sees a Spanish name.
"""

from collections.abc import Mapping
from typing import Any

import yaml

from argos_common.errors import ArgosError

CHALLENGE_KEYS: Mapping[str, str] = {
    "titulo": "title",
    "objetivo": "objective",
    "obligacion": "obligation",
    "clase_de_activo": "asset_class",
    "sonda": "probe",
    "tipo": "kind",
    "objeto": "target",
    "por_conector": "by_connector",
    "sentencia": "statement",
    "parametros": "params",
    "criterio": "criterion",
    "umbral": "threshold",
    "campo": "field",
    "operador": "operator",
    "valor": "value",
    "paquete": "package",
    "evidencia": "evidence",
    "capturar": "capture",
    "minimizacion": "minimisation",
    "severidad": "severity",
    "muestreo": "sampling",
    "confianza": "confidence",
    "margen": "margin",
    "aprobacion_requerida": "approval_required",
    "precondiciones": "preconditions",
    "coste_estimado": "estimated_cost",
    "sondas": "probes",
    "filas": "rows",
}
CHALLENGE_VALUES: Mapping[str, Mapping[str, str]] = {
    "severity": {"critica": "critical", "alta": "high", "media": "medium", "baja": "low"},
    "capture": {
        "resultado": "result",
        "recuentos": "counts",
        "hashes": "hashes",
        "configuracion": "configuration",
        "muestra_hasheada": "hashed_sample",
    },
    "preconditions": {
        "sujeto_sintetico_inyectado": "synthetic_subject_injected",
        "documento_del_cliente_aportado": "client_document_provided",
    },
}
# Keys whose contents are opaque to the translation: bind names and typed references are free text.
OPAQUE = frozenset({"params", "input_map", "target"})
# Connector identifiers are names, not fields: the variant below them is translated, they are not.
BY_CONNECTOR = "by_connector"
# English names that have no Spanish form because they are already identifiers of the format.
ENGLISH_ONLY = frozenset(
    {"id", "version", "selector", "criterion", "opa", "asset_class", "input_map", "target"}
)


class TranslationError(ArgosError):
    """A key or value of the challenge is outside the closed translation table."""


class _StrictLoader(yaml.SafeLoader):
    """Rejects duplicate keys, like the editorial loader of the ontology."""


def _mapping_without_duplicates(loader: _StrictLoader, node: yaml.MappingNode) -> dict[str, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise TranslationError(f"duplicate key in the challenge: {key!r}")
        seen.add(key)
    return dict(loader.construct_pairs(node, deep=True))


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_without_duplicates
)


def read_challenge(text: str) -> dict[str, Any]:
    document = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - strict loader, no tags
    if not isinstance(document, dict):
        raise TranslationError("a challenge is a YAML mapping")
    return document


def _english_keys() -> frozenset[str]:
    return frozenset(CHALLENGE_KEYS.values())


def _translate_value(field: str, value: Any, key: str) -> Any:
    table = CHALLENGE_VALUES.get(field)
    if table is None or not isinstance(value, str):
        return value
    if value in table.values():
        return value
    if value not in table:
        raise TranslationError(f"unknown value for {key}: {value!r}")
    return table[value]


def to_internal(document: Mapping[str, Any]) -> dict[str, Any]:
    """The same challenge with English keys and values; unknown names are errors."""
    known = _english_keys()
    result: dict[str, Any] = {}
    for key, value in document.items():
        if key in CHALLENGE_KEYS:
            field = CHALLENGE_KEYS[key]
        elif key in known or key in ENGLISH_ONLY:
            field = str(key)
        else:
            raise TranslationError(f"unknown key in the challenge: {key!r}")
        if field in result:
            raise TranslationError(f"the field {field!r} is given twice, in Spanish and in English")
        if field in OPAQUE:
            result[field] = value
        elif field == BY_CONNECTOR and isinstance(value, dict):
            result[field] = {name: to_internal(variant) for name, variant in value.items()}
        elif isinstance(value, dict):
            result[field] = to_internal(value)
        elif isinstance(value, list):
            result[field] = [_translate_value(field, item, str(key)) for item in value]
        else:
            result[field] = _translate_value(field, value, str(key))
    return result


def _spanish_key(field: str) -> str:
    for spanish, english in CHALLENGE_KEYS.items():
        if english == field:
            return spanish
    return field


def _spanish_value(field: str, value: Any) -> Any:
    table = CHALLENGE_VALUES.get(field)
    if table is None or not isinstance(value, str):
        return value
    for spanish, english in table.items():
        if english == value:
            return spanish
    raise TranslationError(f"unknown value for {field}: {value!r}")


def to_editorial(document: Mapping[str, Any]) -> dict[str, Any]:
    """The same challenge with the Spanish names, for whoever edits it."""
    result: dict[str, Any] = {}
    for field, value in document.items():
        key = _spanish_key(str(field))
        if field in OPAQUE:
            result[key] = value
        elif field == BY_CONNECTOR and isinstance(value, dict):
            result[key] = {name: to_editorial(variant) for name, variant in value.items()}
        elif isinstance(value, dict):
            result[key] = to_editorial(value)
        elif isinstance(value, list):
            result[key] = [_spanish_value(str(field), item) for item in value]
        else:
            result[key] = _spanish_value(str(field), value)
    return result
