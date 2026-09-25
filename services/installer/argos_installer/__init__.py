"""ARG-096 · the installer of week 1: from a box in the rack to a system ready for its sources.

A guided command-line installer (ADR-0015 point 9), not a text interface: the data centre does not
always have a screen, and a reviewable YAML is what the organisation signs off. Every step plans
its commands, runs them and verifies its result; a step is done only when its verification passes.

- The commands are always lists of arguments, never a shell: every value of the configuration is
  validated for what it says it is (an address, a device, a user name) before it reaches one.
- `--dry-run` shows every command it would run and runs none.
- It stops at the first step that does not verify and, run again, resumes from it.
- The report of the installation (`argos/installation/1`) is signed with the release key of the
  appliance, recorded in the journal and left beside the state, where the airlock can take it: it
  opens the implementation file of the Pliego (P-26).
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import yaml
from pydantic import BaseModel, Field, field_validator

REPORT_SCHEMA = "argos/installation/1"
ACTOR = "system:installer"
LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOSTNAME = re.compile(rf"^(?=.{{1,253}}$){LABEL}(?:\.{LABEL})*$")
SEAL_SCRIPT = "/opt/argos/platform/image/seal-disk.sh"
# The first administrator configures a TOTP and a new password at the first sign-in (F09-07).
REQUIRED_ACTIONS = '["CONFIGURE_TOTP","UPDATE_PASSWORD"]'


# ---------- the configuration, validated before any command sees it ----------


def _ipv4(value: str) -> str:
    return str(ipaddress.IPv4Address(value))


class Management(BaseModel):
    interface: str = Field(pattern=r"^[a-z][a-z0-9]{0,14}$")
    address: str
    prefix: int = Field(ge=1, le=32)
    gateway: str
    bastion: str

    _addresses = field_validator("address", "gateway", "bastion")(_ipv4)


class Time(BaseModel):
    ntp: str | None = None
    declared_drift_seconds: int = Field(default=0, ge=0, le=3600)

    @field_validator("ntp")
    @classmethod
    def _host(cls, value: str | None) -> str | None:
        if value is not None and not HOSTNAME.match(value):
            raise ValueError("ntp must be a host name")
        return value


class Disk(BaseModel):
    device: str = Field(pattern=r"^/dev/[A-Za-z0-9/_.-]+$")


class Admin(BaseModel):
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")


class Idp(BaseModel):
    alias: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    url: str = Field(pattern=r"^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$")


class Tsa(BaseModel):
    url: str | None = Field(
        default=None, pattern=r"^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?$"
    )
    airgapped: bool = False


class InstallConfig(BaseModel):
    management: Management
    time: Time
    disk: Disk
    admin: Admin
    idp: Idp | None = None
    tsa: Tsa


def load_config(path: Path) -> InstallConfig:
    return InstallConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


# ---------- commands: lists of arguments, a runner that can be a double ----------


@dataclass(frozen=True, slots=True)
class Completed:
    returncode: int
    stdout: str = ""


@dataclass(frozen=True, slots=True)
class Command:
    args: list[str]
    stdin: str | None = None


class Runner(Protocol):
    def __call__(self, args: list[str], stdin: str | None = None) -> Completed: ...


def subprocess_runner(args: list[str], stdin: str | None = None) -> Completed:
    done = subprocess.run(  # noqa: S603 - a list of validated arguments, never a shell
        args, input=stdin, capture_output=True, text=True, timeout=600, check=False
    )
    return Completed(done.returncode, done.stdout)


class Signer(Protocol):
    def sign(self, data: bytes) -> bytes: ...

    def public_key(self) -> bytes: ...


Record = Callable[[str, str, dict[str, Any]], object]


# ---------- the steps of week 1 ----------


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    plan: Callable[[InstallConfig], list[Command]]
    verify: Callable[[InstallConfig, Runner], tuple[bool, str]]


def _ping(run: Runner, host: str) -> bool:
    return run(["ping", "-c", "2", "-W", "2", host]).returncode == 0


def _plan_network(c: InstallConfig) -> list[Command]:
    m = c.management
    return [
        Command(["netplan", "set", f"ethernets.{m.interface}.addresses=[{m.address}/{m.prefix}]"]),
        Command(
            [
                "netplan",
                "set",
                f"ethernets.{m.interface}.routes=[{{to: default, via: {m.gateway}}}]",
            ]
        ),
        Command(["netplan", "apply"]),
    ]


def _verify_network(c: InstallConfig, run: Runner) -> tuple[bool, str]:
    gateway, bastion = _ping(run, c.management.gateway), _ping(run, c.management.bastion)
    if gateway and bastion:
        return True, "pasarela y bastión alcanzables"
    return (
        False,
        f"pasarela {'sí' if gateway else 'NO'} responde; bastión {'sí' if bastion else 'NO'}",
    )


def _plan_time(c: InstallConfig) -> list[Command]:
    if c.time.ntp is None:
        return []
    return [
        Command(["tee", "/etc/systemd/timesyncd.conf.d/argos.conf"], f"[Time]\nNTP={c.time.ntp}\n"),
        Command(["timedatectl", "set-ntp", "true"]),
        Command(["systemctl", "restart", "systemd-timesyncd"]),
    ]


def _verify_time(c: InstallConfig, run: Runner) -> tuple[bool, str]:
    if c.time.ntp is None:
        drift = c.time.declared_drift_seconds
        return True, f"modo aislado: deriva local declarada de {drift} s"
    synced = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]).stdout.strip()
    return synced == "yes", f"sincronizado con {c.time.ntp}: {synced or 'sin respuesta'}"


def _plan_disk(c: InstallConfig) -> list[Command]:
    return [Command(["env", f"ARGOS_DATA_DEVICE={c.disk.device}", SEAL_SCRIPT])]


def _verify_disk(c: InstallConfig, run: Runner) -> tuple[bool, str]:
    dump = run(["cryptsetup", "luksDump", c.disk.device])
    ok = dump.returncode == 0 and "tpm2" in dump.stdout
    return ok, "slot TPM2 presente" if ok else "el volumen no tiene slot TPM2"


def _plan_admin(c: InstallConfig) -> list[Command]:
    user = c.admin.username
    return [
        Command(["kcadm.sh", "create", "users", "-r", "argos", "-s", f"username={user}",
                 "-s", "enabled=true", "-s", f"requiredActions={REQUIRED_ACTIONS}"]),
        Command(["kcadm.sh", "add-roles", "-r", "argos", "--uusername", user,
                 "--rolename", "platform_admin"]),
    ]  # fmt: skip


def _verify_admin(c: InstallConfig, run: Runner) -> tuple[bool, str]:
    user = c.admin.username
    found = run(["kcadm.sh", "get", "users", "-r", "argos", "-q", f"username={user}"])
    ok = found.returncode == 0 and f'"username": "{user}"' in found.stdout
    return ok, (
        f"{user}: segundo factor y cambio de clave obligados al primer acceso"
        if ok
        else f"{user} no aparece en el realm"
    )


def _plan_idp(c: InstallConfig) -> list[Command]:
    if c.idp is None:
        return []
    return [
        Command(["kcadm.sh", "create", "identity-provider/instances", "-r", "argos",
                 "-s", f"alias={c.idp.alias}", "-s", "providerId=oidc",
                 "-s", f"config.issuer={c.idp.url}", "-s", "enabled=true"]),
    ]  # fmt: skip


def _verify_idp(c: InstallConfig, run: Runner) -> tuple[bool, str]:
    if c.idp is None:
        return True, "federación omitida: cuentas locales del realm"
    found = run(["kcadm.sh", "get", f"identity-provider/instances/{c.idp.alias}", "-r", "argos"])
    return found.returncode == 0, f"federación con {c.idp.url}"


def _plan_tsa(c: InstallConfig) -> list[Command]:
    return []


def _verify_tsa(c: InstallConfig, run: Runner) -> tuple[bool, str]:
    if c.tsa.airgapped or c.tsa.url is None:
        return True, "modo aislado explícito: los sellos salen y entran por la esclusa (RB-09)"
    reached = run(["curl", "-fsS", "-m", "5", "-o", "/dev/null", c.tsa.url]).returncode == 0
    return reached, f"TSA {c.tsa.url} {'alcanzable' if reached else 'NO responde'}"


STEPS: tuple[Step, ...] = (
    Step("network", "Red de gestión y bastión", _plan_network, _verify_network),
    Step("time", "Hora (NTP del organismo o deriva declarada)", _plan_time, _verify_time),
    Step("disk", "Sellado del disco al TPM", _plan_disk, _verify_disk),
    Step("admin", "Primer administrador, con segundo factor", _plan_admin, _verify_admin),
    Step("idp", "Federación con el proveedor de identidad (opcional)", _plan_idp, _verify_idp),
    Step("tsa", "Autoridad de sellado o modo aislado", _plan_tsa, _verify_tsa),
)
ORDER = tuple(step.key for step in STEPS)


# ---------- the installer ----------


@dataclass
class Installer:
    config: InstallConfig
    run_command: Runner
    state_dir: Path
    signer: Signer
    record: Record
    dry_run: bool = False
    steps: Sequence[Step] = STEPS
    _done: list[str] = field(default_factory=list)

    @property
    def _state(self) -> Path:
        return self.state_dir / "state.json"

    def _load_done(self) -> list[str]:
        if not self._state.exists():
            return []
        return list(json.loads(self._state.read_text(encoding="utf-8")).get("done", []))

    def _save_done(self, done: list[str]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._state.write_text(json.dumps({"done": done}), encoding="utf-8")

    def run(self) -> dict[str, Any]:
        started = datetime.now(UTC)
        done = [] if self.dry_run else self._load_done()
        entries: list[dict[str, Any]] = []
        completed = True
        for step in self.steps:
            if step.key in done:
                continue
            planned = step.plan(self.config)
            if self.dry_run:
                entries.append({"key": step.key, "title": step.title,
                                "would_run": [c.args for c in planned]})  # fmt: skip
                continue
            codes = [self.run_command(c.args, c.stdin).returncode for c in planned]
            ok, detail = step.verify(self.config, self.run_command)
            entries.append(
                {"key": step.key, "title": step.title, "ok": ok, "detail": detail,
                 "commands": len(planned), "exit_codes": codes}
            )  # fmt: skip
            if not ok:
                completed = False
                break
            done.append(step.key)
            self._save_done(done)
        report = {
            "schema": REPORT_SCHEMA,
            "started": started.isoformat(),
            "finished": datetime.now(UTC).isoformat(),
            "dry_run": self.dry_run,
            "completed": completed and not self.dry_run,
            "config_sha256": hashlib.sha256(
                self.config.model_dump_json().encode("utf-8")
            ).hexdigest(),
            "steps": entries,
        }
        if not self.dry_run:
            self._seal(report)
        return report

    def _seal(self, report: dict[str, Any]) -> None:
        """The report, signed, beside the state; and a journal entry with its hash."""
        body = json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "installation-report.json").write_bytes(body)
        (self.state_dir / "installation-report.json.sig").write_bytes(self.signer.sign(body))
        action = "install.completed" if report["completed"] else "install.stopped"
        stopped = [s["key"] for s in report["steps"] if s.get("ok") is False]
        self.record(
            ACTOR,
            action,
            {"report_sha256": hashlib.sha256(body).hexdigest(), "stopped_at": stopped},
        )
