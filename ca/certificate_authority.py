"""
Nonce Certificate Authority
Real X.509 certificate generation using cryptography library.
Issues SPIFFE-compliant SVIDs (SPIFFE Verifiable Identity Documents).
"""

import os
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509 import UniformResourceIdentifier


CA_KEY_PATH  = os.path.join(os.path.dirname(__file__), "ca_key.pem")
CA_CERT_PATH = os.path.join(os.path.dirname(__file__), "ca_cert.pem")

TRUST_DOMAIN = "nonce.dev"


def _load_or_create_ca():
    """Load existing CA key+cert, or bootstrap a new one on first run."""
    if os.path.exists(CA_KEY_PATH) and os.path.exists(CA_CERT_PATH):
        with open(CA_KEY_PATH, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        with open(CA_CERT_PATH, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        return key, cert

    # Bootstrap: generate EC P-256 CA key
    key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME,             "Nonce Root CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME,       "Nonce.dev"),
        x509.NameAttribute(NameOID.COUNTRY_NAME,            "US"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    os.makedirs(os.path.dirname(CA_KEY_PATH), exist_ok=True)
    with open(CA_KEY_PATH, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(CA_CERT_PATH, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return key, cert


# Module-level singletons
_CA_KEY, _CA_CERT = _load_or_create_ca()


def get_ca_cert_pem() -> str:
    return _CA_CERT.public_bytes(serialization.Encoding.PEM).decode()


def issue_svid(spiffe_id: str, ttl_minutes: int = 60) -> dict:
    """
    Issue a real SPIFFE SVID:
      - Generates a fresh EC P-256 key pair for the agent
      - Issues an X.509 cert signed by the Nonce CA with SPIFFE URI SAN
      - Returns PEM cert, PEM private key, serial number, validity window
    """
    agent_key = ec.generate_private_key(ec.SECP256R1())

    now     = datetime.datetime.utcnow()
    expires = now + datetime.timedelta(minutes=ttl_minutes)

    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, spiffe_id),
        ]))
        .issuer_name(_CA_CERT.subject)
        .public_key(agent_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(expires)
        # SPIFFE requires the ID in the URI SAN
        .add_extension(
            x509.SubjectAlternativeName([
                UniformResourceIdentifier(spiffe_id),
            ]),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=False, crl_sign=False,
                content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=True,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.CLIENT_AUTH,
                ExtendedKeyUsageOID.SERVER_AUTH,
            ]),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(_CA_KEY.public_key()),
            critical=False,
        )
        .sign(_CA_KEY, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem  = agent_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()

    serial_hex = format(cert.serial_number, 'x').upper()
    serial_fmt = ':'.join(serial_hex[i:i+2] for i in range(0, len(serial_hex), 2))

    return {
        "certificate_pem": cert_pem,
        "private_key_pem": key_pem,
        "serial":          serial_fmt,
        "not_before":      now.isoformat() + "Z",
        "not_after":       expires.isoformat() + "Z",
        "issuer":          "CN=Nonce Root CA, O=Nonce.dev",
        "subject":         spiffe_id,
        "key_algorithm":   "EC P-256",
        "signature_alg":   "SHA256withECDSA",
    }


def verify_svid_cert(cert_pem: str) -> dict:
    """
    Verify a certificate against the Nonce CA.
    Returns {valid, reason, spiffe_id, expired}
    """
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        now  = datetime.datetime.utcnow()

        # Check expiry
        if cert.not_valid_after_utc.replace(tzinfo=None) < now:
            return {"valid": False, "reason": "certificate_expired", "expired": True}

        # Verify signature against CA cert
        _CA_CERT.public_key().verify(
            cert.signature,
            cert.tbs_certificate_bytes,
            ec.ECDSA(cert.signature_hash_algorithm),
        )

        # Extract SPIFFE ID from SAN
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        uris = san.value.get_values_for_type(UniformResourceIdentifier)
        spiffe_id = next((u for u in uris if u.startswith("spiffe://")), None)

        return {
            "valid":      True,
            "reason":     None,
            "expired":    False,
            "spiffe_id":  spiffe_id,
            "not_after":  cert.not_valid_after_utc.isoformat(),
        }
    except Exception as e:
        return {"valid": False, "reason": f"verification_failed: {str(e)}", "expired": False}
