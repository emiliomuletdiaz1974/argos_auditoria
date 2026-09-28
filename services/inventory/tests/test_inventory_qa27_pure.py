"""QA-27 · classification at its edges (quality review QA-034, 035, 041, 042).

- QA-034: column names in Spanish (accents, ñ), plurals and an acronym glued to a word are read.
- QA-035: every category of personal data the classifier gives is selected by some asset class,
  or no obligation can ever apply to it.
- QA-041: a column a person rejected is never classified again by the model on its own.
- QA-042: the evidence of a structural flow is its best candidate, whatever order the graph
  returned the rows in; a column name with `|` does not break the signature.
"""

import re
import unicodedata
from pathlib import Path

import pytest

from argos_inventory.classify.assisted import Proposal, triage
from argos_inventory.classify.dictionary import match_column_name, name_tokens
from argos_inventory.flows.detect import structural_candidates
from argos_inventory.graph.model import CATEGORIES

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("teléfono", "contact_data"),
        (unicodedata.normalize("NFD", "teléfono"), "contact_data"),
        ("dirección_postal", "location_data"),
        ("contraseña", "technical_credential"),
        ("DNIPaciente", "official_identifier"),
        ("emails", "contact_data"),
        ("api_keys", "technical_credential"),
    ],
)
def test_names_in_spanish_plurals_and_acronyms_are_read(name: str, category: str) -> None:
    assert match_column_name(name) == category, name_tokens(name)


def test_every_personal_category_has_an_asset_class() -> None:
    selected = set(
        re.findall(r'"category": "([^"]+)"', (REPO / "library/ontology/asset-classes/base.ttl")
                   .read_text(encoding="utf-8"))
    )  # fmt: skip
    personal = [c for c in CATEGORIES if c != "no_personal_data"]
    orphans = [c for c in personal if not any(c.startswith(prefix) for prefix in selected)]
    assert orphans == [], "a category no asset class selects is outside every obligation"


def test_a_column_a_person_rejected_is_never_accepted_by_the_model_alone() -> None:
    proposal = Proposal("k1", "contact_data", 0.97, "looks like a phone")
    result = triage([proposal], frozenset({"k1"}), rejected=frozenset({"k1"}))
    assert result.accepted == () and result.review == () and result.ignored == (proposal,)


def test_the_best_structural_candidate_comes_first_in_any_order() -> None:
    common = {f"c{i}|special_category.health" for i in range(10)}
    signatures = {
        ("S1", "p.t9"): frozenset(common | {"x|contact_data"}),
        ("S2", "q.t9"): frozenset(common | {"x|contact_data"}),
        ("S1", "p.t2"): frozenset(common | {"y|contact_data"}),
        ("S2", "q.t2"): frozenset(common | {"z|contact_data"}),
    }
    forward = structural_candidates(signatures)
    backward = structural_candidates(dict(reversed(list(signatures.items()))))
    assert forward[0] == backward[0]
    assert forward[0][2] == max(score for _, _, score in forward)


def test_a_column_name_with_a_bar_keeps_its_category() -> None:
    from argos_inventory.flows.detect import signature_category

    assert signature_category("weird|name|special_category.health") == "special_category.health"
