"""ARG-096 · the installer of week 1, with a double of every command (F10-10).

The installer walks the steps in order, verifies each one, stops at the first that does not verify
and resumes from it; it never uses a shell, it changes nothing in a dry run, and its report is
signed and verifies.
"""

import ast
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from argos_common.release import verify_signature
from argos_installer import ORDER, Completed, InstallConfig, Installer, load_config

CONFIG: dict[str, Any] = {
    "management": {
        "interface": "mgmt0",
        "address": "10.10.0.21",
        "prefix": 24,
        "gateway": "10.10.0.1",
        "bastion": "10.10.0.5",
    },
    "time": {"ntp": "ntp.organismo.example"},
    "disk": {"device": "/dev/disk/by-partlabel/argos-data"},
    "admin": {"username": "admin.organismo"},
    "idp": None,
    "tsa": {"url": "https://tsa.organismo.example"},
}
OUTPUTS = {
    "timedatectl": "yes",
    "cryptsetup": "Tokens:\n  0: systemd-tpm2",
    "kcadm.sh": '[{"username": "admin.organismo"}]',
}


class Commands:
    """Every command succeeds unless its first word is in `failing`; each call is remembered."""

    def __init__(self, failing: set[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.failing = failing or set()

    def __call__(self, args: list[str], stdin: str | None = None) -> Completed:
        assert isinstance(args, list) and all(isinstance(a, str) for a in args)
        self.calls.append(args)
        return Completed(1 if args[0] in self.failing else 0, OUTPUTS.get(args[0], ""))


class Signer:
    def __init__(self) -> None:
        self._key = Ed25519PrivateKey.generate()

    def sign(self, data: bytes) -> bytes:
        return self._key.sign(data)

    def public_key(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _installer(
    tmp_path: Path, commands: Commands, config: dict[str, Any] = CONFIG, **kwargs: Any
) -> Installer:
    return Installer(
        InstallConfig.model_validate(config),
        commands,
        state_dir=tmp_path,
        signer=kwargs.pop("signer", Signer()),
        record=lambda *entry: None,
        **kwargs,
    )


def test_the_steps_run_in_the_order_of_week_1(tmp_path: Path) -> None:
    report = _installer(tmp_path, Commands()).run()
    assert [step["key"] for step in report["steps"]] == list(ORDER)
    assert ORDER[:3] == ("network", "time", "disk")
    assert all(step["ok"] for step in report["steps"]), report["steps"]


def test_it_stops_at_the_first_step_that_fails_and_resumes_from_it(tmp_path: Path) -> None:
    report = _installer(tmp_path, Commands(failing={"ping"})).run()
    assert [s["key"] for s in report["steps"]] == ["network"]
    assert report["steps"][0]["ok"] is False
    assert report["completed"] is False
    # The network is fixed; the next run starts again at the step that failed.
    report = _installer(tmp_path, Commands()).run()
    assert report["steps"][0]["key"] == "network"
    assert report["completed"] is True
    # And a third run has nothing left to do.
    again = Commands()
    assert _installer(tmp_path, again).run()["steps"] == []
    assert again.calls == []


def test_a_dry_run_changes_nothing(tmp_path: Path) -> None:
    commands = Commands()
    report = _installer(tmp_path, commands, dry_run=True).run()
    assert commands.calls == []
    assert report["dry_run"] is True
    planned = [c for step in report["steps"] for c in step["would_run"]]
    assert ["netplan", "apply"] in planned
    assert not (tmp_path / "state.json").exists()


def test_the_report_is_signed_and_verifies(tmp_path: Path) -> None:
    signer = Signer()
    _installer(tmp_path, Commands(), signer=signer).run()
    report = (tmp_path / "installation-report.json").read_bytes()
    signature = (tmp_path / "installation-report.json.sig").read_bytes()
    verify_signature(report, signature, signer.public_key())
    assert json.loads(report)["schema"] == "argos/installation/1"


def test_an_isolated_appliance_declares_its_drift_and_its_airlock(tmp_path: Path) -> None:
    config = {
        **CONFIG,
        "time": {"ntp": None, "declared_drift_seconds": 2},
        "tsa": {"airgapped": True},
    }
    steps = {s["key"]: s for s in _installer(tmp_path, Commands(), config).run()["steps"]}
    assert "deriva" in steps["time"]["detail"]
    assert "aislado" in steps["tsa"]["detail"]


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("management", "address", "10.0.0.1; reboot"),
        ("management", "interface", "eth0 && rm"),
        ("admin", "username", "a b"),
        ("time", "ntp", "ntp.example; reboot"),
    ],
)
def test_a_value_that_is_not_what_it_says_is_refused(section: str, key: str, value: str) -> None:
    config = json.loads(json.dumps(CONFIG))
    config[section][key] = value
    with pytest.raises(ValueError):
        InstallConfig.model_validate(config)


def test_no_shell_anywhere_in_the_installer() -> None:
    package = Path(__file__).resolve().parents[1] / "argos_installer"
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.keyword) and node.arg == "shell":
                pytest.fail(f"{path.name} passes shell=")


def test_the_configuration_is_read_from_a_reviewable_yaml(tmp_path: Path) -> None:
    path = tmp_path / "installer.yaml"
    path.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    assert load_config(path).management.gateway == "10.10.0.1"


def test_the_example_of_the_repository_is_a_valid_configuration() -> None:
    example = (
        Path(__file__).resolve().parents[3] / "platform" / "operation" / "installer.example.yaml"
    )
    assert load_config(example).admin.username == "admin.organismo"


def test_the_command_line_dry_run_prints_the_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from argos_installer.cli import main

    path = tmp_path / "installer.yaml"
    path.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    assert main(["--config", str(path), "--dry-run", "--state-dir", str(tmp_path / "state")]) == 0
    printed = capsys.readouterr().out
    assert '["netplan", "apply"]' in printed
    assert "nothing was changed" in printed
    assert not (tmp_path / "state").exists()
