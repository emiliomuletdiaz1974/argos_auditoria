"""Prepare the simulated file and directory sources before make dev starts the containers.

Generates, deterministically and outside git: the SMB file tree, the S3 bucket directory, the
development TLS certificates for LDAPS and the directory LDIF. Every name and value is synthetic.

Usage: uv run python tools/prepare_dev_sources.py
"""

import hashlib
import ipaddress
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

SOURCES = Path(__file__).resolve().parents[1] / "deploy" / "dev" / "sources"
BASE_DN = "dc=hosp,dc=local"
EPOCH = datetime(2026, 9, 1, tzinfo=UTC).timestamp()  # fixed reference so ages are reproducible
YEAR_S = 31_557_600
PAYLOADS: dict[str, bytes] = {
    "pdf": b"%PDF-1.4\n% synthetic document\n",
    "docx": b"PK\x03\x04synthetic-ooxml",
    "png": b"\x89PNG\r\n\x1a\nsynthetic",
    "jpg": b"\xff\xd8\xff\xe0synthetic",
    "dcm": b"\x00" * 128 + b"DICMsynthetic",
    "txt": b"synthetic note without signature\n",
}
MODEL_PAYLOAD = b"\x08\x07\x12\x07synthetic-onnx"
DEPARTMENTS = ("radiology", "cardiology", "admin")


def _write(path: Path, content: bytes, age_years: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    stamp = EPOCH - age_years * YEAR_S
    os.utime(path, (stamp, stamp))


def build_file_tree(root: Path, count: int = 120) -> None:
    shutil.rmtree(root, ignore_errors=True)
    extensions = list(PAYLOADS)
    for i in range(count):
        ext = extensions[i % len(extensions)]
        department = DEPARTMENTS[i % len(DEPARTMENTS)]
        year = 2012 + i % 14
        name = f"SYN{i % 40:08d}_{'report' if i % 2 else 'scan'}.{ext}"
        _write(root / department / str(year) / name, PAYLOADS[ext] + str(i).encode(), i % 15)
    # A model file for the AI discovery detector (F03-00): only its extension is a signal.
    _write(root / "admin" / "models" / "readmission_v3.onnx", MODEL_PAYLOAD, 1)


def build_bucket(root: Path, count: int = 60) -> None:
    shutil.rmtree(root, ignore_errors=True)
    extensions = list(PAYLOADS)
    for i in range(count):
        ext = extensions[(i * 5) % len(extensions)]
        path = root / "exports" / f"batch{i % 6}" / f"SYN{i:08d}.{ext}"
        _write(path, PAYLOADS[ext] + str(i).encode(), i % 12)


def tree_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest[path.relative_to(root).as_posix()] = f"{digest}:{int(path.stat().st_mtime)}"
    return manifest


def _strict_chain_present(directory: Path) -> bool:
    """Python 3.13 verifies strictly: a CA without key identifiers breaks every LDAPS handshake."""
    try:
        ca = x509.load_pem_x509_certificate((directory / "ca.crt").read_bytes())
        server = x509.load_pem_x509_certificate((directory / "server.crt").read_bytes())
        ca.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
        server.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
    except (OSError, ValueError, x509.ExtensionNotFound):
        return False
    return True


def build_certificates(directory: Path) -> None:
    if _strict_chain_present(directory):
        return
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ARGOS dev sources CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
        .sign(ca_key, hashes.SHA256())
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "source-ldap")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName("source-ldap"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), False)
        .sign(ca_key, hashes.SHA256())
    )
    (directory / "ca.crt").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    (directory / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory / "server.key").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )


def _user_dn(i: int) -> str:
    return f"uid=syn.user{i},ou=people,{BASE_DN}"


def _group_dn(name: str) -> str:
    return f"cn={name},ou=groups,{BASE_DN}"


def _group(name: str, members: list[str]) -> str:
    lines = "".join(f"member: {m}\n" for m in members)
    return f"dn: {_group_dn(name)}\nobjectClass: groupOfNames\ncn: {name}\n{lines}"


def build_ldif(directory: Path, users: int = 300) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    blocks = [
        f"dn: ou=people,{BASE_DN}\nobjectClass: organizationalUnit\nou: people\n",
        f"dn: ou=groups,{BASE_DN}\nobjectClass: organizationalUnit\nou: groups\n",
    ]
    for i in range(1, users + 1):
        blocks.append(
            f"dn: {_user_dn(i)}\n"
            "objectClass: inetOrgPerson\n"
            f"uid: syn.user{i}\ncn: Synthetic Person {i}\nsn: Person{i}\n"
            f"mail: syn.user{i}@hosp.local\n"
            f"employeeType: {'service' if i % 25 == 0 else 'staff'}\n"
        )
    blocks.append(_group("privileged", [_user_dn(i) for i in range(1, 6)] + [_group_dn("tier0")]))
    blocks.append(_group("tier0", [_user_dn(i) for i in range(6, 11)] + [_group_dn("privileged")]))
    blocks.append(_group("helpdesk", [_user_dn(i) for i in range(11, 21)]))
    (directory / "50-synthetic.ldif").write_text("\n".join(blocks), encoding="utf-8")


def main() -> int:
    build_file_tree(SOURCES / "files" / "clinical")
    build_bucket(SOURCES / "s3" / "clinical-archive")
    build_certificates(SOURCES / "certs")
    build_ldif(SOURCES / "ldap")
    print("development file and directory sources prepared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
