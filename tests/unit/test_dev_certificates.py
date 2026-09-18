"""The development CA passes the strict X.509 checks Python 3.13 applies by default."""

import importlib.util
from pathlib import Path

from cryptography import x509

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("prepare", ROOT / "tools" / "prepare_dev_sources.py")
assert _spec is not None and _spec.loader is not None
prepare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prepare)


def _load(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


def test_the_chain_carries_the_key_identifiers_strict_verification_needs(tmp_path: Path) -> None:
    prepare.build_certificates(tmp_path)
    ca, server = _load(tmp_path / "ca.crt"), _load(tmp_path / "server.crt")
    server.verify_directly_issued_by(ca)
    ca_ski = ca.extensions.get_extension_for_class(x509.SubjectKeyIdentifier).value
    server_aki = server.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier).value
    assert server_aki.key_identifier == ca_ski.digest
    assert ca.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign
    server_usage = server.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert x509.oid.ExtendedKeyUsageOID.SERVER_AUTH in server_usage


def test_certificates_from_before_are_rebuilt(tmp_path: Path) -> None:
    # A CA written by the earlier version lacks the identifiers; keeping it keeps LDAPS broken.
    prepare.build_certificates(tmp_path)
    (tmp_path / "server.crt").write_text("stale", encoding="utf-8")
    (tmp_path / "ca.crt").write_bytes(b"")
    prepare.build_certificates(tmp_path)
    assert _load(tmp_path / "ca.crt").extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
