"""LDAP / AD connector (ARG-018) against an ldap3 mock with the Active Directory 2012 R2 schema."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ldap3 import MOCK_SYNC, OFFLINE_AD_2012_R2, Connection, Server

from argos_connector.probes import ProbeSpec
from argos_connector.testing import InMemoryJournal, assert_no_write_surface, make_context
from argos_ldap.connector import LdapConnector, to_datetime

SYSTEM_ID = "0190f000-0000-7000-8000-000000000001"
BASE = "dc=hosp,dc=local"
FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
USER_CLASSES = ["top", "person", "organizationalPerson", "user"]
GROUP_CLASSES = ["top", "group"]


def _filetime(moment: datetime) -> int:
    return int((moment - FILETIME_EPOCH).total_seconds() * 10_000_000)


def _user(i: int) -> str:
    return f"cn=user{i},ou=people,{BASE}"


def _group(name: str) -> str:
    return f"cn={name},ou=groups,{BASE}"


def _mock_directory(read_only: bool = True) -> Connection:
    server = Server("mock_ad", get_info=OFFLINE_AD_2012_R2)
    conn = Connection(
        server,
        user=f"cn=reader,ou=svc,{BASE}",
        password="reader",
        client_strategy=MOCK_SYNC,
        read_only=read_only,
        raise_exceptions=True,
    )
    conn.strategy.add_entry(
        f"cn=reader,ou=svc,{BASE}", {"objectClass": USER_CLASSES, "userPassword": "reader"}
    )
    now = datetime.now(UTC)
    for i in range(1, 121):
        flags = 512 | (0x2 if i % 10 == 0 else 0) | (0x10000 if i % 7 == 0 else 0)
        attributes: dict[str, Any] = {
            "objectClass": USER_CLASSES,
            "sAMAccountName": f"user{i}",
            "userAccountControl": flags,
            "lastLogonTimestamp": _filetime(now - timedelta(days=i)),
            "pwdLastSet": _filetime(now - timedelta(days=2 * i)),
        }
        if i % 25 == 0:
            attributes["servicePrincipalName"] = f"HTTP/app{i}.hosp.local"
        conn.strategy.add_entry(_user(i), attributes)
    conn.strategy.add_entry(
        _group("Domain Admins"),
        {"objectClass": GROUP_CLASSES, "member": [_user(1), _group("Tier0")]},
    )
    conn.strategy.add_entry(
        _group("Tier0"),
        {"objectClass": GROUP_CLASSES, "member": [_user(2), _user(3), _group("Domain Admins")]},
    )
    conn.strategy.add_entry(
        _group("Helpdesk"), {"objectClass": GROUP_CLASSES, "member": [_user(4)]}
    )
    conn.bind()
    return conn


class MockLdap(LdapConnector):
    mock: Connection

    def _connect(self) -> Connection:
        return self.mock


def _connector(read_only: bool = True) -> tuple[MockLdap, InMemoryJournal]:
    journal = InMemoryJournal()
    connector = MockLdap(SYSTEM_ID, {"base_dn": BASE}, make_context(journal=journal))
    connector.mock = _mock_directory(read_only)
    connector.open()
    return connector, journal


def test_scan_aggregates_account_flags() -> None:
    connector, journal = _connector()
    result = connector.execute(ProbeSpec("scan_schema", BASE))
    assert result.data == {
        "users": 121,
        "disabled": 12,
        "password_never_expires": 17,
        "service_like": 4,
        "groups": 3,
    }
    assert (journal.emitted[0].spec.statement or "").startswith(f"SEARCH base={BASE}")


def test_count_with_a_validated_filter() -> None:
    connector, _ = _connector()
    services = ProbeSpec("count", BASE, params={"ldap_filter": "(servicePrincipalName=*)"})
    assert connector.execute(services).data["count"] == 4
    one = ProbeSpec("count", BASE, params={"ldap_filter": "(sAMAccountName=user7)"})
    assert connector.execute(one).data["count"] == 1


@pytest.mark.parametrize("bad", ["(&(objectClass=user)", "objectClass=user", ""])
def test_invalid_filters_are_refused_before_journaling(bad: str) -> None:
    connector, journal = _connector()
    with pytest.raises(ValueError):
        connector.execute(ProbeSpec("count", BASE, params={"ldap_filter": bad}))
    assert journal.records == []


def test_sample_returns_ages_and_digests_only() -> None:
    connector, _ = _connector()
    result = connector.execute(ProbeSpec("sample", BASE, params={"k": 10}))
    assert result.data["n"] == 10
    entries = result.data["entries"]
    ages = [e["days_since_logon"] for e in entries if e["days_since_logon"] is not None]
    assert len(ages) >= 9 and all(age >= 0 for age in ages)
    assert "cn=user" not in repr(result)


def test_transitive_membership_survives_cycles() -> None:
    connector, _ = _connector()
    spec = ProbeSpec("check_config", BASE, params={"group_dn": _group("Domain Admins")})
    result = connector.execute(spec)
    assert result.data["transitive_members"] == 3
    assert result.data["nested_groups"] == 1
    assert len(result.data["dn_digests"]) == 3


def test_writable_connection_is_refused() -> None:
    connector = MockLdap(SYSTEM_ID, {"base_dn": BASE}, make_context())
    connector.mock = _mock_directory(read_only=False)
    with pytest.raises(RuntimeError, match="read-only"):
        connector.open()


def test_to_datetime_accepts_filetime_and_datetime() -> None:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    converted = to_datetime(_filetime(moment))
    assert converted is not None and abs(converted - moment) < timedelta(seconds=1)
    assert to_datetime(moment) == moment
    assert to_datetime(0) is None and to_datetime(None) is None


def test_no_write_surface() -> None:
    assert_no_write_surface(LdapConnector)


def _real_connection_kwargs(
    monkeypatch: pytest.MonkeyPatch, config: dict[str, Any]
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def spy(server: Server, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs, server=server)
        return captured

    monkeypatch.setattr("argos_ldap.connector.Connection", spy)
    credentials = {"host": "dc01.hosp.local", "bind_dn": "cn=argos", "password": "dev-only"}
    LdapConnector(SYSTEM_ID, config, make_context(credentials=credentials))._connect()
    return captured


def test_referrals_are_never_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    # A referral to another host would receive the simple bind, in clear text if it is ldap://.
    kwargs = _real_connection_kwargs(monkeypatch, {"base_dn": BASE})
    assert kwargs["auto_referrals"] is False
    assert kwargs["server"].allowed_referral_hosts == []


def test_network_timeouts_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = _real_connection_kwargs(monkeypatch, {"base_dn": BASE})
    assert kwargs["server"].connect_timeout == 10
    assert kwargs["receive_timeout"] == 30
    kwargs = _real_connection_kwargs(
        monkeypatch, {"base_dn": BASE, "connect_timeout_s": 3, "receive_timeout_s": 5}
    )
    assert kwargs["server"].connect_timeout == 3
    assert kwargs["receive_timeout"] == 5
