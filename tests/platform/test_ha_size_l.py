"""ARG-095 · the size L with quorum, validated statically (F10-09; applied in F10-92)."""

from pathlib import Path

import yaml

PATRONI = Path(__file__).resolve().parents[2] / "platform" / "ha" / "size-l" / "patroni.yaml"


def _config() -> dict[str, object]:
    return dict(yaml.safe_load(PATRONI.read_text(encoding="utf-8")))


def test_the_consensus_is_three_nodes_over_tls() -> None:
    etcd = _config()["etcd3"]
    assert isinstance(etcd, dict)
    assert len(etcd["hosts"]) == 3
    assert etcd["protocol"] == "https"


def test_replication_is_synchronous_and_strict() -> None:
    dcs = _config()["bootstrap"]["dcs"]  # type: ignore[index]
    assert dcs["synchronous_mode"] is True
    assert dcs["synchronous_mode_strict"] is True
    assert dcs["failsafe_mode"] is True


def test_no_connection_over_the_network_without_tls_and_a_password() -> None:
    rules = _config()["postgresql"]["pg_hba"]  # type: ignore[index]
    network = [rule for rule in rules if not rule.startswith("local")]
    assert all(rule.startswith("hostssl") or rule.endswith("reject") for rule in network)
    assert not any("trust" in rule for rule in rules)
    assert "hostnossl all all all reject" in rules


def test_the_rest_api_asks_for_a_client_certificate() -> None:
    assert _config()["restapi"]["verify_client"] == "required"  # type: ignore[index]
