"""ARG-035 · data space ODRL policies are parsed within a bounded profile and become challenges."""

from typing import Any

import pytest

from argos_ontology.odrl import (
    TEMPLATES,
    Constraint,
    PolicyError,
    Rule,
    parse_policy,
    to_challenges,
)

ASSET = "urn:dataspace:asset:synthetic-oncology-cohort"
UID = "urn:dataspace:policy:0001"


def _policy(**rules: Any) -> dict[str, Any]:
    return {
        "@context": "http://www.w3.org/ns/odrl.jsonld",
        "@type": "Offer",
        "uid": UID,
        "target": ASSET,
        **rules,
    }


RETENTION = {
    "action": "odrl:delete",
    "constraint": [
        {"leftOperand": "odrl:elapsedTime", "operator": "odrl:lteq", "rightOperand": "P1Y2M10D"}
    ],
}
PURPOSE = {
    "action": {"@id": "http://www.w3.org/ns/odrl/2/use"},
    "constraint": [
        {
            "leftOperand": "purpose",
            "operator": "isAnyOf",
            "rightOperand": ["research", {"@value": "public-health"}],
        }
    ],
}
NO_SHARE = {"action": "odrl:distribute"}


def test_the_supported_profile_is_parsed_into_rules_without_prefixes() -> None:
    policy = parse_policy(
        _policy(permission=[PURPOSE], prohibition=[NO_SHARE], obligation=[RETENTION])
    )
    assert policy.uid == UID
    assert policy.target == ASSET
    assert policy.unsupported == ()
    assert policy.rules == (
        Rule(
            "permission",
            "use",
            (
                Constraint("purpose", "isAnyOf", "research"),
                Constraint("purpose", "isAnyOf", "public-health"),
            ),
        ),
        Rule("prohibition", "distribute", ()),
        Rule("duty", "delete", (Constraint("elapsedTime", "lteq", "P1Y2M10D"),)),
    )


def test_verifiable_rules_become_parametrised_challenges_on_the_space_asset() -> None:
    policy = parse_policy(
        _policy(permission=[PURPOSE], prohibition=[NO_SHARE], obligation=[RETENTION])
    )
    assert to_challenges(policy) == [
        {
            "template": "ds-usage-purpose",
            "params": {"asset": ASSET, "allowed_purposes": ["research", "public-health"]},
            "policy_uid": UID,
            "finding_only": False,
        },
        {
            "template": "ds-no-redistribution",
            "params": {"asset": ASSET},
            "policy_uid": UID,
            "finding_only": False,
        },
        {
            "template": "ds-asset-retention",
            "params": {"asset": ASSET, "max_days": 365 + 60 + 10},
            "policy_uid": UID,
            "finding_only": False,
        },
    ]


def _constrained(kind: str, action: str, left: str, right: object) -> dict[str, Any]:
    constraint = {"leftOperand": left, "operator": "lteq", "rightOperand": right}
    return {kind: [{"action": action, "constraint": [constraint]}]}


@pytest.mark.parametrize(
    ("rules", "clause"),
    [
        (_constrained("permission", "use", "count", 5), "permission:constraint:count"),
        ({"obligation": [{"action": "compensate"}]}, "obligation:action:compensate"),
        (_constrained("obligation", "delete", "elapsedTime", "PT12H"), "obligation:duration:PT12H"),
        (_constrained("obligation", "delete", "elapsedTime", "P1W"), "obligation:duration:P1W"),
        (_constrained("obligation", "delete", "elapsedTime", "P"), "obligation:duration:P"),
    ],
)
def test_what_the_profile_does_not_cover_is_reported_not_ignored(
    rules: dict[str, Any], clause: str
) -> None:
    policy = parse_policy(_policy(**rules))
    assert policy.unsupported == (clause,)
    assert to_challenges(policy)[-1] == {
        "template": "ds-unverifiable",
        "params": {"asset": ASSET, "clauses": [clause]},
        "policy_uid": UID,
        "finding_only": True,
    }


def test_a_delete_duty_without_a_term_is_unverifiable() -> None:
    policy = parse_policy(_policy(obligation=[{"action": "delete"}]))
    assert [c["template"] for c in to_challenges(policy)] == ["ds-unverifiable"]
    assert policy.unsupported == ("obligation:delete-without-term",)


def test_a_single_rule_object_is_accepted_as_a_one_element_list() -> None:
    policy = parse_policy(_policy(prohibition=NO_SHARE))
    assert policy.rules == (Rule("prohibition", "distribute", ()),)


@pytest.mark.parametrize(
    "document",
    [
        {"target": ASSET, "permission": []},
        {"uid": UID, "permission": []},
        {"uid": UID, "target": ASSET, "permission": [{"constraint": []}]},
        {
            "uid": UID,
            "target": ASSET,
            "permission": [{"action": "use", "constraint": [{"operator": "eq"}]}],
        },
        {"uid": UID, "target": ASSET, "permission": ["use"]},
        ["not", "a", "policy"],
    ],
)
def test_malformed_documents_are_rejected_with_a_policy_error(document: Any) -> None:
    with pytest.raises(PolicyError):
        parse_policy(document)


def test_translation_is_deterministic_and_templates_are_closed() -> None:
    document = _policy(obligation=[RETENTION], permission=[PURPOSE])
    assert to_challenges(parse_policy(document)) == to_challenges(parse_policy(document))
    assert set(TEMPLATES) == {
        "ds-asset-retention",
        "ds-usage-purpose",
        "ds-no-redistribution",
        "ds-unverifiable",
    }
