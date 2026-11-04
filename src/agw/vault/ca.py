from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class IssuedCert:
    certificate_pem: str
    serial_number: str
    fingerprint_sha256: str
    expires_at: datetime


class InternalCA:
    """Development-grade CA backed by files.

    Production deployments should move the signing key into KMS or an HSM.
    """

    _lock = threading.Lock()

    def __init__(self, directory: Path, *, ca_ttl_days: int = 3650) -> None:
        self.directory = Path(directory)
        self.ca_ttl_days = ca_ttl_days
        self.key_path = self.directory / "ca_key.pem"
        self.cert_path = self.directory / "ca_cert.pem"

    def _ensure(self) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            if self.key_path.exists() and self.cert_path.exists():
                key = serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)
                cert = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
                return key, cert  # type: ignore[return-value]

            key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            subject = issuer = x509.Name(
                [x509.NameAttribute(NameOID.COMMON_NAME, "AI Gateway Internal CA")]
            )
            now = datetime.now(UTC)
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=self.ca_ttl_days))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(
                    x509.KeyUsage(
                        digital_signature=True,
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
                .sign(key, hashes.SHA256())
            )
            self.key_path.write_bytes(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
            self.key_path.chmod(0o600)
            self.cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            return key, cert

    @property
    def certificate_pem(self) -> str:
        _, cert = self._ensure()
        return cert.public_bytes(serialization.Encoding.PEM).decode()

    def issue(self, csr_pem: str, *, spiffe_id: str, ttl_hours: int) -> IssuedCert:
        key, ca_cert = self._ensure()
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        if not csr.is_signature_valid:
            raise ValueError("CSR signature is invalid")
        now = datetime.now(UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(hours=ttl_hours))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
            )
            .add_extension(
                x509.SubjectAlternativeName([x509.UniformResourceIdentifier(spiffe_id)]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        der = cert.public_bytes(serialization.Encoding.DER)
        return IssuedCert(
            certificate_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
            serial_number=format(cert.serial_number, "x"),
            fingerprint_sha256=hashlib.sha256(der).hexdigest(),
            expires_at=cert.not_valid_after_utc.replace(tzinfo=None),
        )
