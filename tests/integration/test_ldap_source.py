"""ARG-018 · LDAP connector over LDAPS against the simulated OpenLDAP directory."""

import ssl
from datetime import UTC, datetime

import pytest
from ldap3 import NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPConnectionIsReadOnlyError

from argos_connector.probes import ProbeSpec
from argos_ldap.connector import LdapConnector

from .sources import ROOT, open_source_connector

pytestmark = pytest.mark.integration
BASE = "dc=hosp,dc=local"
CA = str(ROOT / "deploy" / "dev" / "sources" / "certs" / "ca.crt")


def _admin() -> Connection:
    # ldap3 matches the host only against DNS names, not IP SANs: accept the certificate's name.
    tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=CA, valid_names=["localhost"])
    server = Server("127.0.0.1", port=1636, use_ssl=True, tls=tls, get_info=NONE)
    return Connection(server, user=f"cn=admin,{BASE}", password="dev-only-admin", auto_bind=True)


def test_directory_probes_without_any_change(migrated_db: str) -> None:
    started = datetime.now(UTC).strftime("%Y%m%d%H%M%SZ")
    connector = open_source_connector("dev-directory-ldap", LdapConnector, migrated_db)
    try:
        scan = connector.execute(ProbeSpec("scan_schema", BASE))
        assert scan.ok and scan.data["users"] >= 300 and scan.data["groups"] >= 3
        one_filter = {"ldap_filter": "(uid=syn.user7)"}
        one = connector.execute(ProbeSpec("count", BASE, params=one_filter))
        assert one.data["count"] == 1
        group = {"group_dn": f"cn=privileged,ou=groups,{BASE}"}
        privileged = connector.execute(ProbeSpec("check_config", BASE, params=group))
        assert privileged.data["transitive_members"] == 10
        assert privileged.data["nested_groups"] == 1
        with pytest.raises(LDAPConnectionIsReadOnlyError):
            connector.connection.delete(f"uid=syn.user1,ou=people,{BASE}")
    finally:
        connector.close()
    admin = _admin()
    admin.search(BASE, f"(|(modifyTimestamp>={started})(createTimestamp>={started}))", SUBTREE)
    assert admin.entries == []
    admin.unbind()
