"""LDAP / Active Directory connector: identities, groups and effective privileged membership.

Component ARG-018. The session is LDAPS with CA validation and ldap3's read_only flag.
"""

import ssl
from collections import deque
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from ldap3 import BASE, NO_ATTRIBUTES, NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPInvalidFilterError, LDAPNoSuchObjectResult
from ldap3.operation.search import parse_filter

from argos_connector.base import Connector
from argos_connector.probes import ProbeSpec

UAC_DISABLED = 0x2
UAC_DONT_EXPIRE_PASSWORD = 0x10000
GROUP_CLASSES = frozenset({"group", "groupofnames", "groupofuniquenames"})
MAX_GROUP_NODES = 10_000
# Each member read is a BASE search against the directory, all under the probe's one permit.
DEFAULT_MAX_GROUP_READS = 1_000
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
_USER_FLAGS = ["userAccountControl", "servicePrincipalName"]
_USER_AGES = ["userAccountControl", "lastLogonTimestamp", "pwdLastSet"]


def to_datetime(value: Any) -> datetime | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    ticks = int(value)
    if ticks <= 0:
        return None
    return _FILETIME_EPOCH + timedelta(microseconds=ticks / 10)


def _first_int(value: Any) -> int:
    if isinstance(value, list):
        value = value[0] if value else 0
    return int(value or 0)


def validate_ldap_filter(value: str) -> str:
    if not value.startswith("(") or not value.endswith(")"):
        raise ValueError(f"invalid LDAP filter: {value!r}")
    try:
        parse_filter(value, None, False, False, None, False)
    except LDAPInvalidFilterError:
        raise ValueError(f"invalid LDAP filter: {value!r}") from None
    return value


class LdapConnector(Connector):
    kind = "directory"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._conn: Connection | None = None

    @property
    def connection(self) -> Connection:
        if self._conn is None:
            raise RuntimeError("connector is not open: call open() first")
        return self._conn

    @property
    def base_dn(self) -> str:
        return str(self.config["base_dn"])

    @property
    def user_filter(self) -> str:
        return validate_ldap_filter(str(self.config.get("user_filter", "(objectClass=user)")))

    @property
    def group_filter(self) -> str:
        return validate_ldap_filter(str(self.config.get("group_filter", "(objectClass=group)")))

    # ---------- lifecycle ----------
    def _connect(self) -> Connection:
        credentials = self.context.credentials
        # ldap3 matches the host only against the certificate's DNS names, never its IP SANs:
        # when the directory is reached by address, the expected names come from configuration.
        valid_names = self.config.get("tls_valid_names") or None
        tls = Tls(
            validate=ssl.CERT_REQUIRED,
            ca_certs_file=self.config.get("ca_file"),
            valid_names=valid_names,
        )
        server = Server(
            credentials["host"],
            port=int(credentials.get("port", "636")),
            use_ssl=True,
            tls=tls,
            get_info=NONE,
            # Referrals are never followed: ldap3 would repeat the simple bind against any host
            # the directory names, in clear text when the referral is ldap://.
            allowed_referral_hosts=[],
            connect_timeout=int(self.config.get("connect_timeout_s", 10)),
        )
        return Connection(
            server,
            user=credentials["bind_dn"],
            password=credentials["password"],
            read_only=True,
            auto_bind=True,
            auto_referrals=False,
            receive_timeout=int(self.config.get("receive_timeout_s", 30)),
            raise_exceptions=True,
        )

    def open(self) -> None:
        connection = self._connect()
        if not connection.read_only:
            raise RuntimeError("LDAP connection must be read-only")
        if not connection.bound:
            connection.bind()
        self._conn = connection

    def close(self) -> None:
        if self._conn is not None:
            self._conn.unbind()
            self._conn = None

    # ---------- rendering ----------
    def render(self, spec: ProbeSpec) -> ProbeSpec:
        if spec.kind == "scan_schema":
            detail = f"filter={self.user_filter} filter={self.group_filter}"
        elif spec.kind == "count":
            detail = f"filter={validate_ldap_filter(str(spec.params.get('ldap_filter', '')))}"
        elif spec.kind == "sample":
            detail = f"filter={self.user_filter}"
        elif spec.kind == "check_config":
            group_dn = spec.params.get("group_dn")
            if not group_dn:
                raise ValueError("check_config needs group_dn")
            detail = f"expand member from={group_dn}"
        else:
            return spec
        return replace(spec, statement=f"SEARCH base={self.base_dn} scope=subtree {detail}")

    # ---------- probes ----------
    def _paged(self, search_filter: str, attributes: Any) -> Iterator[dict[str, Any]]:
        for entry in self.connection.extend.standard.paged_search(
            self.base_dn,
            search_filter,
            SUBTREE,
            attributes=attributes,
            paged_size=int(self.config.get("page_size", 500)),
            generator=True,
        ):
            if entry.get("type") == "searchResEntry":
                yield entry

    def _do_scan_schema(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        summary = {
            "users": 0,
            "disabled": 0,
            "password_never_expires": 0,
            "service_like": 0,
            "groups": 0,
        }
        for entry in self._paged(self.user_filter, _USER_FLAGS):
            attributes = entry.get("attributes", {})
            summary["users"] += 1
            flags = _first_int(attributes.get("userAccountControl"))
            summary["disabled"] += bool(flags & UAC_DISABLED)
            summary["password_never_expires"] += bool(flags & UAC_DONT_EXPIRE_PASSWORD)
            summary["service_like"] += bool(attributes.get("servicePrincipalName"))
        summary["groups"] = sum(1 for _ in self._paged(self.group_filter, NO_ATTRIBUTES))
        return summary, summary["users"]

    def _do_count(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        search_filter = str(spec.params["ldap_filter"])
        n = sum(1 for _ in self._paged(search_filter, NO_ATTRIBUTES))
        return {"count": n, "filter": search_filter}, n

    def _do_sample(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        limit = min(int(spec.params.get("k", 100)), self.context.budget.max_rows_per_probe)
        hasher, now = self.context.hasher, datetime.now(UTC)
        entries: list[dict[str, Any]] = []
        for entry in self._paged(self.user_filter, _USER_AGES):
            if len(entries) >= limit:
                break
            attributes = entry.get("attributes", {})
            last_logon = to_datetime(attributes.get("lastLogonTimestamp"))
            password_set = to_datetime(attributes.get("pwdLastSet"))
            flags = _first_int(attributes.get("userAccountControl"))
            entries.append(
                {
                    "dn_digest": hasher.digest(str(entry["dn"]).lower()),
                    "disabled": bool(flags & UAC_DISABLED),
                    "days_since_logon": (now - last_logon).days if last_logon else None,
                    "password_age_days": (now - password_set).days if password_set else None,
                }
            )
        return {"n": len(entries), "entries": entries}, len(entries)

    def _read_node(self, dn: str) -> tuple[list[str], set[str]] | None:
        try:
            self.connection.search(
                dn, "(objectClass=*)", BASE, attributes=["member", "objectClass"]
            )
        except LDAPNoSuchObjectResult:
            return None
        if not self.connection.response:
            return None
        attributes = self.connection.response[0].get("attributes", {})
        members = attributes.get("member") or []
        classes = {str(c).lower() for c in attributes.get("objectClass") or []}
        listed = members if isinstance(members, list) else [members]
        return [str(m) for m in listed], classes

    def _do_check_config(self, spec: ProbeSpec) -> tuple[dict[str, Any], int]:
        group_dn = str(spec.params["group_dn"])
        groups, users = {group_dn.lower()}, set[str]()
        pending, visited_nodes = deque([group_dn]), 0
        max_reads = int(self.config.get("max_group_reads", DEFAULT_MAX_GROUP_READS))
        while pending:
            node = self._read_node(pending.popleft())
            if node is None:
                continue
            for member in node[0]:
                key = member.lower()
                if key in groups or key in users:
                    continue
                visited_nodes += 1
                if visited_nodes > min(MAX_GROUP_NODES, max_reads):
                    raise RuntimeError("group expansion exceeded the node cap")
                child = self._read_node(member)
                if child is not None and child[1] & GROUP_CLASSES:
                    groups.add(key)
                    pending.append(member)
                elif child is not None:
                    users.add(key)
        hasher = self.context.hasher
        data = {
            "group_dn_digest": hasher.digest(group_dn.lower()),
            "transitive_members": len(users),
            "nested_groups": len(groups) - 1,
            "dn_digests": sorted(hasher.digest(u) for u in users),
        }
        return data, len(users)
