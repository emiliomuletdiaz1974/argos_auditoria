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

REPO = Path(__file__).resolve().parents[3]
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
    "site": {
        "size": "S",
        "data_interface": "data0",
        "sources": ["10.20.0.8"],
        "limits_file": str(REPO / "platform" / "operation" / "sizes.yaml"),
    },
}
SITE = REPO / "tests" / "fixtures" / "site"
OUTPUTS = {
    "timedatectl": "yes",
    "cryptsetup": "Tokens:\n  0: systemd-tpm2",
    # kcadm.sh prints JSON the way Jackson does: a space before each colon.
    "kcadm.sh get": '[ {\n  "id" : "7f1c",\n  "username" : "admin.organismo",\n'
    '  "requiredActions" : [ "CONFIGURE_TOTP", "UPDATE_PASSWORD" ]\n} ]',
    "kcadm.sh get-roles": '[ {\n  "id" : "a1",\n  "name" : "platform_admin"\n} ]',
    "ipmitool": (SITE / "ipmitool_sensor_list.txt").read_text(encoding="utf-8"),
    "ethtool": (SITE / "ethtool_10g.txt").read_text(encoding="utf-8"),
    "ping": (SITE / "ping_ok.txt").read_text(encoding="utf-8"),
    "nvidia-smi": (SITE / "nvidia_smi_l40s.txt").read_text(encoding="utf-8"),
}


class Commands:
    """Every command succeeds unless its first word is in `failing`; each call is remembered."""

    def __init__(self, failing: set[str] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.failing = failing or set()

    def __call__(self, args: list[str], stdin: str | None = None) -> Completed:
        assert isinstance(args, list) and all(isinstance(a, str) for a in args)
        self.calls.append(args)
        output = OUTPUTS.get(" ".join(args[:2]), OUTPUTS.get(args[0], ""))
        return Completed(1 if args[0] in self.failing else 0, output)


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
    assert ORDER[:4] == ("network", "site", "time", "disk")
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
    # And a third run has nothing left to do: it runs nothing and its report still holds every
    # step the earlier runs did (QA-083).
    again = Commands()
    report = _installer(tmp_path, again).run()
    assert again.calls == []
    assert report["completed"] is True
    assert [s["key"] for s in report["steps"] if s["ok"]] == list(ORDER)


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
        ("site", "data_interface", "data0; reboot"),
        ("site", "sources", ["10.20.0.8 && rm"]),
        ("site", "size", "XL"),
    ],
)
def test_a_value_that_is_not_what_it_says_is_refused(section: str, key: str, value: Any) -> None:
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


def test_a_room_that_does_not_give_stops_the_installation_and_says_why(tmp_path: Path) -> None:
    hot = (SITE / "ipmitool_sensor_list_hot_single_psu.txt").read_text(encoding="utf-8")

    class HotRoom(Commands):
        def __call__(self, args: list[str], stdin: str | None = None) -> Completed:
            done = super().__call__(args, stdin)
            return Completed(done.returncode, hot) if args[0] == "ipmitool" else done

    report = _installer(tmp_path, HotRoom()).run()
    assert not report["completed"]
    [site] = [step for step in report["steps"] if step["key"] == "site"]
    assert not site["ok"]
    assert "unfit" in site["detail"] and "31" in site["detail"]
    assert [step["key"] for step in report["steps"]][-1] == "site"


# --- QA-21: the key reaches the operator, the admin is really checked, the report adds up -----


class Console:
    """The console of the operator: what runs here is shown, never captured into the report."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], stdin: str | None = None) -> Completed:
        self.calls.append(args)
        print("    RECOVERY KEY (write it down): fhjk-vnrd-cbtl-hjgv")
        return Completed(0, "")


class SealedAfterwards(Commands):
    """The volume has no TPM slot until the seal script ran."""

    def __init__(self, console: Console) -> None:
        super().__init__()
        self.console = console

    def __call__(self, args: list[str], stdin: str | None = None) -> Completed:
        if args[0] == "cryptsetup":
            self.calls.append(args)
            return Completed(0, OUTPUTS["cryptsetup"] if self.console.calls else "Tokens:\n")
        return super().__call__(args, stdin)


def test_the_seal_script_runs_on_the_console_and_its_key_never_reaches_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    console = Console()
    commands = SealedAfterwards(console)
    report = _installer(tmp_path, commands, run_on_console=console).run()
    assert report["completed"], report["steps"]
    assert [c[-1] for c in console.calls] == ["/opt/argos/platform/image/seal-disk.sh"]
    assert all("seal-disk.sh" not in " ".join(c) for c in commands.calls)
    assert "fhjk" in capsys.readouterr().out, "the operator sees the key"
    assert "fhjk" not in (tmp_path / "installation-report.json").read_text(encoding="utf-8")


def test_a_volume_already_sealed_is_not_sealed_again(tmp_path: Path) -> None:
    console = Console()
    _installer(tmp_path, Commands(), run_on_console=console).run()
    assert console.calls == [], "sealing again would add a recovery key nobody asked for"


@pytest.mark.parametrize(
    ("key", "output", "missing"),
    [
        ("kcadm.sh get-roles", "[ ]", "platform_admin"),
        ("kcadm.sh get", '[ {\n  "username" : "admin.organismo",\n  "requiredActions" : [ ]\n} ]',
         "CONFIGURE_TOTP"),
        ("kcadm.sh get", "[ ]", "no aparece"),
    ],
)  # fmt: skip
def test_the_admin_is_verified_on_what_keycloak_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, output: str, missing: str
) -> None:
    monkeypatch.setitem(OUTPUTS, key, output)
    report = _installer(tmp_path, Commands()).run()
    [admin] = [s for s in report["steps"] if s["key"] == "admin"]
    assert admin["ok"] is False
    assert missing in admin["detail"]


def test_a_changed_configuration_starts_the_installation_again(tmp_path: Path) -> None:
    _installer(tmp_path, Commands()).run()
    changed = json.loads(json.dumps(CONFIG))
    changed["disk"]["device"] = "/dev/disk/by-partlabel/argos-other"
    commands = Commands()
    _installer(tmp_path, commands, config=changed).run()
    assert ["netplan", "apply"] in commands.calls, "nothing done under another configuration counts"
