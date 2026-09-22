"""Rendering the templates of `templates.yaml` (ARG-079).

The language is deliberately tiny —placeholders, the whole event, a lookup by a field— so a template
cannot run anything: it only rearranges what the event already carries.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

TEMPLATES_FILE = Path(__file__).with_name("templates.yaml")
WHOLE_EVENT = "$event"
AS_JSON = "{$json}"
LOOKUP = "$map"


class TemplateError(ValueError):
    """The template does not exist or cannot be read."""


class _Blank(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return ""


@lru_cache(maxsize=1)
def load_templates(path: Path = TEMPLATES_FILE) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not loaded:
        raise TemplateError(f"{path} does not hold templates")
    return loaded


def _fill(shape: Any, event: dict[str, Any]) -> Any:
    if shape == WHOLE_EVENT:
        return dict(event)
    if shape == AS_JSON:
        return json.dumps(event, ensure_ascii=False, sort_keys=True)
    if isinstance(shape, str):
        return shape.format_map(_Blank({k: "" if v is None else v for k, v in event.items()}))
    if isinstance(shape, dict) and LOOKUP in shape:
        chosen = event.get(str(shape[LOOKUP]))
        return dict(shape.get("values", {})).get(chosen, shape.get("default"))
    if isinstance(shape, dict):
        return {key: _fill(value, event) for key, value in shape.items()}
    if isinstance(shape, list):
        return [_fill(item, event) for item in shape]
    return shape


def render(template: str, event: dict[str, Any]) -> Any:
    templates = load_templates()
    if template not in templates:
        raise TemplateError(f"unknown template {template!r}: one of {sorted(templates)}")
    return _fill(templates[template], event)
