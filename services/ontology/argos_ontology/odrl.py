"""ODRL 2.2 policies of data spaces: bounded-profile parser and challenge translation (ARG-035).

Data spaces (Gaia-X, EHDS, Catena-X) carry usage conditions as ODRL policies. We read the profile
real spaces use, not full ODRL: purpose, elapsed time, date and spatial constraints, and delete and
notify duties. Whatever falls outside the profile is not ignored: it becomes an explicit
"not automatically verifiable" finding (deviation note ARG-034-040).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SUPPORTED_LEFT_OPERANDS = frozenset({"purpose", "elapsedTime", "dateTime", "spatial"})
SUPPORTED_DUTIES = frozenset({"delete", "notify"})
RULE_KINDS = (("permission", "permission"), ("prohibition", "prohibition"), ("obligation", "duty"))
REDISTRIBUTION_ACTIONS = frozenset({"distribute", "share"})
TEMPLATES = ("ds-asset-retention", "ds-usage-purpose", "ds-no-redistribution", "ds-unverifiable")

ISO_DURATION = re.compile(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)D)?")
_LOCAL_NAME = re.compile(r"[^:/#]+$")


class PolicyError(ValueError):
    """The document is not an ODRL policy we can even read (missing uid, target or action)."""


@dataclass(frozen=True, slots=True)
class Constraint:
    left: str
    operator: str
    right: str


@dataclass(frozen=True, slots=True)
class Rule:
    kind: str
    action: str
    constraints: tuple[Constraint, ...]


@dataclass(frozen=True, slots=True)
class Policy:
    uid: str
    target: str
    rules: tuple[Rule, ...]
    unsupported: tuple[str, ...]


def _local(term: str) -> str:
    """`odrl:delete`, `http://www.w3.org/ns/odrl/2/delete` and `delete` are the same term."""
    match = _LOCAL_NAME.search(term.strip())
    return match.group(0) if match else term


def _term(value: object, what: str) -> str:
    if isinstance(value, Mapping):
        value = value.get("@id", value.get("id"))
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{what} must be a non-empty IRI or term")
    return _local(value)


def _values(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        if isinstance(item, Mapping):
            item = item.get("@value", item.get("@id"))
        if item is None:
            raise PolicyError("rightOperand has no value")
        out.append(str(item))
    return out


def _as_list(value: object, kind: str) -> list[Any]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return value
    raise PolicyError(f"{kind} must be a rule object or a list of rules")


def duration_days(iso: str) -> int | None:
    """Days of a `PnYnMnD` duration (year = 365, month = 30); None when outside the profile."""
    match = ISO_DURATION.fullmatch(iso)
    if match is None or not any(match.groups()):
        return None
    years, months, days = (int(part or 0) for part in match.groups())
    return years * 365 + months * 30 + days


def _rule(kind: str, raw: object, unsupported: list[str]) -> Rule | None:
    if not isinstance(raw, Mapping):
        raise PolicyError(f"{kind} rule must be an object")
    if "action" not in raw:
        raise PolicyError(f"{kind} rule without action")
    action = _term(raw["action"], "action")
    constraints: list[Constraint] = []
    for item in _as_list(raw.get("constraint", []), "constraint"):
        if (
            not isinstance(item, Mapping)
            or not {"leftOperand", "operator", "rightOperand"} <= item.keys()
        ):
            raise PolicyError(f"{kind} constraint needs leftOperand, operator and rightOperand")
        left = _term(item["leftOperand"], "leftOperand")
        if left not in SUPPORTED_LEFT_OPERANDS:
            unsupported.append(f"{kind}:constraint:{left}")
            continue
        operator = _term(item["operator"], "operator")
        for right in _values(item["rightOperand"]):
            if left == "elapsedTime" and duration_days(right) is None:
                unsupported.append(f"{kind}:duration:{right}")
                continue
            constraints.append(Constraint(left, operator, right))
    if kind == "obligation":
        if action not in SUPPORTED_DUTIES:
            unsupported.append(f"obligation:action:{action}")
            return None
        has_term = any(c.left == "elapsedTime" for c in constraints)
        bad_term = any(clause.startswith("obligation:duration:") for clause in unsupported)
        if action == "delete" and not has_term and not bad_term:
            unsupported.append("obligation:delete-without-term")
    return Rule(dict(RULE_KINDS)[kind], action, tuple(constraints))


def parse_policy(jsonld: object) -> Policy:
    """Read a policy (Offer, Agreement or Set) in the data space profile."""
    if not isinstance(jsonld, Mapping):
        raise PolicyError("policy must be a JSON-LD object")
    uid, target = jsonld.get("uid"), jsonld.get("target")
    if not isinstance(uid, str) or not uid:
        raise PolicyError("policy without uid")
    if isinstance(target, Mapping):
        target = target.get("@id", target.get("uid"))
    if not isinstance(target, str) or not target:
        raise PolicyError("policy without target asset")
    rules: list[Rule] = []
    unsupported: list[str] = []
    for kind, _ in RULE_KINDS:
        for raw in _as_list(jsonld.get(kind, []), kind):
            rule = _rule(kind, raw, unsupported)
            if rule is not None:
                rules.append(rule)
    return Policy(uid=uid, target=target, rules=tuple(rules), unsupported=tuple(unsupported))


def _spec(
    policy: Policy, template: str, params: dict[str, Any], finding_only: bool = False
) -> dict[str, Any]:
    return {
        "template": template,
        "params": {"asset": policy.target, **params},
        "policy_uid": policy.uid,
        "finding_only": finding_only,
    }


def to_challenges(policy: Policy) -> list[dict[str, Any]]:
    """Challenge specifications for phase 05, in rule order; the unverifiable finding goes last."""
    out: list[dict[str, Any]] = []
    for rule in policy.rules:
        if rule.kind == "permission":
            purposes = [c.right for c in rule.constraints if c.left == "purpose"]
            if purposes:
                out.append(_spec(policy, "ds-usage-purpose", {"allowed_purposes": purposes}))
        elif rule.kind == "prohibition" and rule.action in REDISTRIBUTION_ACTIONS:
            out.append(_spec(policy, "ds-no-redistribution", {}))
        elif rule.kind == "duty" and rule.action == "delete":
            terms = [duration_days(c.right) for c in rule.constraints if c.left == "elapsedTime"]
            days = [term for term in terms if term is not None]
            if days:
                out.append(_spec(policy, "ds-asset-retention", {"max_days": min(days)}))
    if policy.unsupported:
        out.append(
            _spec(
                policy, "ds-unverifiable", {"clauses": list(policy.unsupported)}, finding_only=True
            )
        )
    return out
