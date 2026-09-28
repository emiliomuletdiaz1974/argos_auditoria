"""ARG-097 · the check of the room: what the appliance can measure, measured on its first start.

Half of the failed implementations die in the room (an undersized supply, a slow link, a hot
aisle). The appliance measures what it can: inlet temperature, supplies, power and voltage (IPMI),
the real speed of the data link, the latency to the bastion and to the declared sources, and the
GPU. Each value is compared with the limits of the size (`platform/operation/sizes.yaml`, key
`site`) and the result goes into the report of the installation.

- Each analyser is a pure function over the text of its command, tested with reference outputs
  (`tests/fixtures/site`).
- A command that is not there, or an output that says nothing, is `not_measured`: never `fit`.
- The commands are lists of arguments, never a shell.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FIT, UNFIT, NOT_MEASURED = "fit", "unfit", "not_measured"
MISSING = 127  # the exit code of a shell for a command that is not there
LIMIT_KEYS = (
    "inlet_min_c",
    "inlet_max_c",
    "voltage_min",
    "voltage_max",
    "min_supplies",
    "power_max_w",
    "link_min_gbps",
    "latency_max_ms",
    "gpu_min_count",
    "gpu_min_total_gib",
)
Run = Callable[[list[str]], Any]


def site_limits(path: Path, size: str) -> dict[str, float]:
    sizes = yaml.safe_load(path.read_text(encoding="utf-8"))["sizes"]
    if size not in sizes:
        raise ValueError(f"unknown size {size!r}: the sizes are {sorted(sizes)}")
    site = sizes[size]["site"]
    return {key: site[key] for key in LIMIT_KEYS}


BTU_PER_WATT = 3.412


def prerequisites(path: Path, size: str) -> list[dict[str, str]]:
    """The list the organisation answers before shipping (Especificación §5.5), with the figures
    of the size: what the room must give before the appliance leaves."""
    sizes = yaml.safe_load(path.read_text(encoding="utf-8"))["sizes"]
    if size not in sizes:
        raise ValueError(f"unknown size {size!r}: the sizes are {sorted(sizes)}")
    site = sizes[size]["site"]
    watts = int(site["power_max_w"])
    items = {
        "rack": site["rack"],
        "power": f"{watts} W en {site['circuits']} circuitos independientes",
        "heat": f"{round(watts * BTU_PER_WATT)} BTU/h que la climatización debe evacuar",
        "outlets": f"{site['outlets']} tomas, una por fuente de alimentación",
        "ups": f"SAI {site['ups']}, para un apagado ordenado",
        "climate": f"entrada a {site['inlet_min_c']}-{site['inlet_max_c']} °C, "
        "flujo frontal-trasero despejado",
        "network": f"enlace de datos de {site['link_min_gbps']} Gbps en VLAN dedicada, "
        f"latencia < {site['latency_max_ms']} ms a las fuentes, IPMI en red de gestión aislada",
    }
    return [{"item": item, "criterion": criterion} for item, criterion in items.items()]


# ---------- analysers: pure functions over the text of each command ----------


def parse_ping(text: str) -> float | None:
    """The average round trip in ms, or None when no reply came back (iputils and busybox)."""
    found = re.search(r"=\s*[\d.]+/([\d.]+)/[\d.]+(?:/[\d.]+)?\s*ms", text)
    return float(found[1]) if found else None


def parse_ping_loss(text: str) -> float | None:
    """The packet loss in percent, or None when the summary does not say it."""
    found = re.search(r"([\d.]+)%\s*packet loss", text)
    return float(found[1]) if found else None


def link_detected(text: str) -> bool:
    return re.search(r"Link detected:\s*yes", text) is not None


def parse_ethtool(text: str) -> float | None:
    """The speed of the link in Gbps, or None when the link is down or its speed unknown."""
    if not re.search(r"Link detected:\s*yes", text):
        return None
    found = re.search(r"Speed:\s*(\d+)\s*Mb/s", text)
    return int(found[1]) / 1000 if found else None


PRESENCE = 0x01
# failure, predictive failure, input lost, input lost or out of range, out of range, config error
SUPPLY_FAULTS = 0x7E


def supply_healthy(state: str) -> bool:
    """A power supply sensor state of `ipmitool sensor list` (`0x0100`): its high byte carries the
    offsets of the IPMI power supply sensor. Healthy is present and without any fault; `na` is
    not a supply that works."""
    try:
        bits = (int(state, 16) >> 8) & 0xFF
    except ValueError:
        return False
    return bool(bits & PRESENCE) and not bits & SUPPLY_FAULTS


def parse_ipmi(text: str) -> dict[str, Any] | None:
    """Inlet temperature, healthy supplies, total input power and the input voltage of each supply.

    Only a sensor named after a supply (`PS1 Voltage`) is its input voltage: the rails of the board
    (12 V, 3.3 V) are not the mains (quality review QA-076). A supply whose power reads `na` leaves
    the total partial, and a partial total is not a measure (QA-075).
    """
    inlet: float | None = None
    healthy: set[str] = set()
    faulty: set[str] = set()
    watts = 0.0
    power_partial = False
    volts: list[float] = []
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 3:
            continue
        name, value, unit = cells[0], cells[1], cells[2]
        supply = re.match(r"^(PS\d+)\s+Status$", name)
        if supply:
            state = cells[3] if len(cells) > 3 else "na"
            (healthy if supply_healthy(state) else faulty).add(supply[1])
            continue
        is_power = unit == "Watts" and "input power" in name.lower()
        try:
            number = float(value)
        except ValueError:
            power_partial = power_partial or is_power
            continue
        if unit == "degrees C" and "inlet" in name.lower():
            inlet = number
        elif is_power:
            watts += number
        elif unit == "Volts" and re.match(r"^PS\d+\b", name):
            volts.append(number)
    if inlet is None and not healthy and not faulty and not volts:
        return None
    return {
        "inlet_c": inlet,
        "supplies": len(healthy),
        "faulty_supplies": sorted(faulty),
        "watts": watts,
        "power_partial": power_partial,
        "volts": volts,
    }


def parse_nvidia(text: str) -> list[tuple[str, float]]:
    """Each GPU and its memory in GiB, from `--query-gpu=name,memory.total --format=csv`."""
    gpus = []
    for line in text.splitlines():
        found = re.match(r"^\s*(.+?),\s*(\d+)\s*MiB\s*$", line)
        if found:
            gpus.append((found[1], round(int(found[2]) / 1024, 1)))
    return gpus


# ---------- measuring: the commands, and what did not answer ----------


@dataclass(frozen=True)
class Measures:
    power: dict[str, Any] | None
    link_gbps: float | None
    link_measured: bool
    latency_ms: dict[str, float | None] = field(default_factory=dict)
    latency_measured: bool = True
    gpus: list[tuple[str, float]] | None = None
    link_up: bool = False
    loss_percent: dict[str, float | None] = field(default_factory=dict)


def _output(run: Run, args: list[str]) -> str | None:
    """The output of a command, or None when the command is not there."""
    try:
        done = run(args)
    except FileNotFoundError:
        return None
    return None if done.returncode == MISSING else str(done.stdout)


def measure(run: Run, data_interface: str, targets: Sequence[str]) -> Measures:
    """Run the commands of the check; `targets` are the bastion first and the declared sources."""
    ipmi = _output(run, ["ipmitool", "sensor", "list"])
    link = _output(run, ["ethtool", data_interface])
    gpu = _output(run, ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv"])
    latency: dict[str, float | None] = {}
    loss: dict[str, float | None] = {}
    latency_measured = True
    for target in targets:
        answer = _output(run, ["ping", "-c", "10", "-i", "0.2", "-q", target])
        if answer is None:
            latency_measured = False
            break
        latency[target] = parse_ping(answer)
        loss[target] = parse_ping_loss(answer)
    return Measures(
        power=parse_ipmi(ipmi) if ipmi is not None else None,
        link_gbps=parse_ethtool(link) if link is not None else None,
        link_measured=link is not None,
        latency_ms=latency,
        latency_measured=latency_measured,
        gpus=parse_nvidia(gpu) if gpu is not None else None,
        link_up=link is not None and link_detected(link),
        loss_percent=loss,
    )


# ---------- the verdict: each check with its reason ----------


def _check(name: str, status: str, reason: str) -> dict[str, str]:
    return {"check": name, "status": status, "reason": reason}


def _power_checks(limits: dict[str, float], power: dict[str, Any] | None) -> list[dict[str, str]]:
    names = ("inlet_temperature", "redundant_supply", "power", "voltage")
    if power is None:
        return [_check(n, NOT_MEASURED, "IPMI no responde: no medido") for n in names]
    checks = []
    inlet = power["inlet_c"]
    if inlet is None:
        checks.append(_check(names[0], NOT_MEASURED, "sin sensor de entrada: no medido"))
    else:
        low, high = limits["inlet_min_c"], limits["inlet_max_c"]
        ok = low <= inlet <= high
        checks.append(
            _check(
                names[0],
                FIT if ok else UNFIT,
                f"entrada a {inlet:g} °C (admitido {low:g}-{high:g} °C)",
            )
        )
    supplies, wanted = power["supplies"], int(limits["min_supplies"])
    faulty = power.get("faulty_supplies", [])
    reason = f"{supplies} fuente(s) sana(s); se piden {wanted}"
    if faulty:
        reason += f"; ausente(s) o con fallo: {', '.join(faulty)}"
    checks.append(_check(names[1], FIT if supplies >= wanted else UNFIT, reason))
    watts, budget = power["watts"], limits["power_max_w"]
    if power.get("power_partial"):
        checks.append(
            _check(names[2], NOT_MEASURED, "alguna fuente no da su potencia (na): no medido")
        )
    elif not watts:
        checks.append(_check(names[2], NOT_MEASURED, "sin lectura de potencia: no medido"))
    else:
        checks.append(
            _check(
                names[2],
                FIT if watts <= budget else UNFIT,
                f"consumo de {watts:g} W; presupuesto de la talla {budget:g} W",
            )
        )
    volts, low, high = power["volts"], limits["voltage_min"], limits["voltage_max"]
    if not volts:
        checks.append(_check(names[3], NOT_MEASURED, "sin lectura de tensión: no medido"))
    else:
        outside = [v for v in volts if not low <= v <= high]
        checks.append(
            _check(
                names[3],
                UNFIT if outside else FIT,
                f"tensiones {', '.join(f'{v:g}' for v in volts)} V (admitido {low:g}-{high:g} V)",
            )
        )
    return checks


def _link_check(limits: dict[str, float], measures: Measures) -> dict[str, str]:
    wanted = limits["link_min_gbps"]
    if not measures.link_measured:
        return _check("data_link", NOT_MEASURED, "ethtool no está: no medido")
    speed = measures.link_gbps
    if speed is None and measures.link_up:
        return _check(
            "data_link", NOT_MEASURED, "enlace activo con velocidad desconocida: no medido"
        )
    if speed is None:
        return _check("data_link", UNFIT, f"enlace de datos caído; se piden {wanted:g} Gbps")
    return _check(
        "data_link",
        FIT if speed >= wanted else UNFIT,
        f"enlace de datos a {speed:g} Gbps; se piden {wanted:g} Gbps",
    )


def _latency_check(limits: dict[str, float], measures: Measures) -> dict[str, str]:
    if not measures.latency_measured:
        return _check("latency", NOT_MEASURED, "ping no está: no medido")
    ceiling = limits["latency_max_ms"]
    bad = []
    for target, ms in measures.latency_ms.items():
        lost = measures.loss_percent.get(target)
        if ms is None:
            bad.append(f"{target} no responde")
        elif lost:
            bad.append(f"{target} pierde el {lost:g} % de los paquetes")
        elif ms >= ceiling:
            bad.append(f"{target} a {ms:g} ms")
    if bad:
        return _check("latency", UNFIT, "; ".join(bad) + f" (límite {ceiling:g} ms)")
    worst = max((ms for ms in measures.latency_ms.values() if ms is not None), default=0.0)
    return _check("latency", FIT, f"peor latencia {worst:g} ms (límite {ceiling:g} ms)")


def _gpu_check(limits: dict[str, float], gpus: list[tuple[str, float]] | None) -> dict[str, str]:
    if gpus is None:
        return _check("gpu", NOT_MEASURED, "nvidia-smi no está: no medido")
    count, total = len(gpus), sum(memory for _, memory in gpus)
    wanted_count, wanted_total = int(limits["gpu_min_count"]), limits["gpu_min_total_gib"]
    names = ", ".join(f"{name} ({memory:g} GiB)" for name, memory in gpus) or "ninguna"
    ok = count >= wanted_count and total >= wanted_total
    return _check(
        "gpu",
        FIT if ok else UNFIT,
        f"{names}; se piden {wanted_count} y {wanted_total:g} GiB en total",
    )


def evaluate(limits: dict[str, float], measures: Measures) -> dict[str, Any]:
    checks = [
        *_power_checks(limits, measures.power),
        _link_check(limits, measures),
        _latency_check(limits, measures),
        _gpu_check(limits, measures.gpus),
    ]
    statuses = {check["status"] for check in checks}
    verdict = UNFIT if UNFIT in statuses else NOT_MEASURED if NOT_MEASURED in statuses else FIT
    return {"verdict": verdict, "checks": checks}
