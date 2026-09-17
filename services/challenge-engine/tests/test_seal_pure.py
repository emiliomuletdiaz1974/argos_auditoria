"""Sello de campaña: mismo contenido, mismo sello; cualquier cambio lo rompe."""

from typing import Any

from argos_challenges.seal import compute_seal, seal_payload

CAMPAIGN: dict[str, Any] = {
    "id": "01920000-0000-7000-8000-0000000000c1",
    "snapshot_hash": "a" * 64,
    "ontology_version": "1.0.0",
    "library_version": "1.0.0",
    "library_sha256": "b" * 64,
    "name": "Campaña",
    "status": "running",
}
HASHES = ["c" * 64, "d" * 64]


def test_the_seal_covers_what_was_measured_and_against_what() -> None:
    payload = seal_payload(CAMPAIGN, HASHES)
    assert set(payload) == {
        "campaign_id",
        "snapshot_hash",
        "ontology_version",
        "library_version",
        "library_sha256",
        "verdicts",
    }
    assert payload["verdicts"] == sorted(HASHES)


def test_the_order_of_the_verdicts_does_not_change_the_seal() -> None:
    assert compute_seal(seal_payload(CAMPAIGN, HASHES)) == compute_seal(
        seal_payload(CAMPAIGN, list(reversed(HASHES)))
    )


def test_changing_a_verdict_the_snapshot_or_a_version_breaks_the_seal() -> None:
    seal = compute_seal(seal_payload(CAMPAIGN, HASHES))
    assert compute_seal(seal_payload(CAMPAIGN, [*HASHES, "e" * 64])) != seal
    assert compute_seal(seal_payload(CAMPAIGN, ["c" * 64, "f" * 64])) != seal
    for field in ("snapshot_hash", "ontology_version", "library_version", "library_sha256"):
        changed = {**CAMPAIGN, field: "changed"}
        assert compute_seal(seal_payload(changed, HASHES)) != seal, field


def test_a_campaign_without_verdicts_still_seals() -> None:
    seal = compute_seal(seal_payload(CAMPAIGN, []))
    assert len(seal) == 64 and seal != compute_seal(seal_payload(CAMPAIGN, HASHES))
