"""ARG-097 · the check of the room, with the reference outputs of each command (F10-11).

What the appliance can measure, measured on its first start: power and a redundant supply, inlet
temperature (IPMI), the real speed of the data link, the latency to the bastion and to the declared
sources, and the GPU. A value out of the limits of the size is `unfit` with its reason; a command
that is not there is `not_measured`, never `fit`.
"""

from pathlib import Path

import pytest

from argos_installer import Completed
from argos_installer.site_check import (
    evaluate,
    measure,
    parse_ethtool,
    parse_ipmi,
    parse_nvidia,
    parse_ping,
    prerequisites,
    site_limits,
)

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "tests" / "fixtures" / "site"
SIZES = REPO / "platform" / "operation" / "sizes.yaml"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_ping_gives_the_average_latency_or_nothing() -> None:
    assert parse_ping(_fixture("ping_ok.txt")) == pytest.approx(0.104)
    assert parse_ping(_fixture("ping_unreachable.txt")) is None


def test_ethtool_gives_the_speed_of_a_link_that_is_up() -> None:
    assert parse_ethtool(_fixture("ethtool_10g.txt")) == 10.0
    assert parse_ethtool(_fixture("ethtool_down.txt")) is None


def test_ipmi_gives_inlet_temperature_supplies_power_and_voltage() -> None:
    power = parse_ipmi(_fixture("ipmitool_sensor_list.txt"))
    assert power == {"inlet_c": 22.0, "supplies": 2, "watts": 780.0, "volts": [230.0, 228.0]}


def test_nvidia_smi_gives_each_gpu_and_its_memory() -> None:
    assert parse_nvidia(_fixture("nvidia_smi_l40s.txt")) == [("NVIDIA L40S", 45.0)]


def _runner(outputs: dict[str, str], missing: frozenset[str] = frozenset()):  # type: ignore[no-untyped-def]
    def run(args: list[str], stdin: str | None = None) -> Completed:
        if args[0] in missing:
            return Completed(127, "")
        return Completed(0, outputs.get(args[0], ""))

    return run


HEALTHY = {
    "ipmitool": _fixture("ipmitool_sensor_list.txt"),
    "ethtool": _fixture("ethtool_10g.txt"),
    "ping": _fixture("ping_ok.txt"),
    "nvidia-smi": _fixture("nvidia_smi_l40s.txt"),
}


def _verdict(outputs: dict[str, str], size: str = "S", missing: frozenset[str] = frozenset()):  # type: ignore[no-untyped-def]
    measures = measure(_runner(outputs, missing), "data0", ["10.10.0.5", "10.20.0.8"])
    return evaluate(site_limits(SIZES, size), measures)


def test_a_healthy_room_is_fit_for_an_s() -> None:
    verdict = _verdict(HEALTHY)
    assert verdict["verdict"] == "fit", verdict["checks"]
    assert {c["check"] for c in verdict["checks"]} >= {
        "inlet_temperature",
        "redundant_supply",
        "power",
        "data_link",
        "latency",
        "gpu",
    }


def test_the_same_room_is_unfit_for_an_m_because_of_its_link() -> None:
    verdict = _verdict(HEALTHY, size="M")
    assert verdict["verdict"] == "unfit"
    [link] = [c for c in verdict["checks"] if c["check"] == "data_link"]
    assert link["status"] == "unfit"
    assert "10" in link["reason"] and "25" in link["reason"]


def test_a_hot_room_with_one_supply_says_why_it_is_unfit() -> None:
    verdict = _verdict({**HEALTHY, "ipmitool": _fixture("ipmitool_sensor_list_hot_single_psu.txt")})
    assert verdict["verdict"] == "unfit"
    unfit = {c["check"]: c["reason"] for c in verdict["checks"] if c["status"] == "unfit"}
    assert "31" in unfit["inlet_temperature"]
    assert "1" in unfit["redundant_supply"]
    assert "2150" in unfit["power"]


def test_a_small_gpu_and_an_unreachable_source_are_unfit() -> None:
    outputs = {**HEALTHY, "nvidia-smi": _fixture("nvidia_smi_small.txt"),
               "ping": _fixture("ping_unreachable.txt")}  # fmt: skip
    unfit = {c["check"] for c in _verdict(outputs)["checks"] if c["status"] == "unfit"}
    assert {"gpu", "latency"} <= unfit


@pytest.mark.parametrize("command", ["ipmitool", "ethtool", "nvidia-smi", "ping"])
def test_a_command_that_is_not_there_is_not_measured_never_fit(command: str) -> None:
    verdict = _verdict(HEALTHY, missing=frozenset({command}))
    statuses = {c["status"] for c in verdict["checks"]}
    assert "not_measured" in statuses
    assert verdict["verdict"] == "not_measured"


def test_every_size_declares_the_limits_of_its_room() -> None:
    for size in ("S", "M", "L"):
        limits = site_limits(SIZES, size)
        assert limits["inlet_max_c"] == 27
        assert limits["latency_max_ms"] == 5
    assert site_limits(SIZES, "M")["link_min_gbps"] == 25


def test_the_list_before_shipping_gives_the_figures_of_each_size() -> None:
    items = {item["item"]: item["criterion"] for item in prerequisites(SIZES, "M")}
    assert set(items) == {"rack", "power", "heat", "outlets", "ups", "climate", "network"}
    assert "2U" in items["rack"]
    assert "1800 W" in items["power"] and "2 circuitos" in items["power"]
    assert "6142 BTU/h" in items["heat"]
    assert "18-27 °C" in items["climate"]
    assert "25 Gbps" in items["network"] and "5 ms" in items["network"]
    assert "4U" in {i["item"]: i["criterion"] for i in prerequisites(SIZES, "L")}["rack"]


def test_the_cli_prints_the_list_before_shipping(capsys: pytest.CaptureFixture[str]) -> None:
    from argos_installer.cli import main

    assert main(["--prerequisites", "S", "--sizes", str(SIZES)]) == 0
    printed = capsys.readouterr().out
    assert "3071 BTU/h" in printed and "torre" in printed
