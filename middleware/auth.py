"""
Nonce Auth Middleware
Handles API key generation, hashing (SHA-256), verification,
and JWT signing/verification with EC P-256 keys.
"""

import hashlib
import hmac
import secrets
import datetime
import json
import base64
import uuid

# ── API Key helpers ───────────────────────────────────────────────────────────

PREFIX = "nonce_sk_live_"

def generate_api_key() -> tuple[str, str, str]:
    """
    Returns (raw_key, key_hash, key_prefix).
    raw_key is shown ONCE to the user and never stored.
    key_hash is stored in the DB and used for verification.
    """
    raw        = PREFIX + secrets.token_hex(24)
    key_hash   = _hash_key(raw)
    key_prefix = raw[:20] + "..."
    return raw, key_hash, key_prefix


def hash_api_key(raw_key: str) -> str:
    return _hash_key(raw_key)


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ── JWT helpers (pure Python, no external lib) ───────────────────────────────
# We use HS256 (HMAC-SHA256) with a per-installation secret for JWTs.
# For production, swap to RS256/ES256 with the CA private key.

import os
_JWT_SECRET = os.environ.get("NONCE_JWT_SECRET", secrets.token_hex(32))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    return base64.urlsafe_b64decode(s + "=" * pad)


def sign_jwt(payload: dict) -> str:
    """Sign a JWT with HS256."""
    import hmac as _hmac
    header  = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body    = _b64url_encode(json.dumps(payload).encode())
    message = f"{header}.{body}"
    sig     = _hmac.new(
        _JWT_SECRET.encode(), message.encode(), hashlib.sha256
    ).digest()
    return f"{message}.{_b64url_encode(sig)}"


def verify_jwt(token: str) -> "dict | None":
    """Verify and decode a JWT. Returns payload or None if invalid/expired."""
    import hmac as _hmac
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, body_b64, sig_b64 = parts
        message = f"{header_b64}.{body_b64}"
        expected_sig = _hmac.new(
            _JWT_SECRET.encode(), message.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected_sig, _b64url_decode(sig_b64)):
            return None
        payload = json.loads(_b64url_decode(body_b64))
        # Check expiry
        if payload.get("exp", 0) < datetime.datetime.utcnow().timestamp():
            return None
        return payload
    except Exception:
        return None


def build_agent_jwt(agent_id: str, spiffe_id: str, org: str,
                    scopes: list, ttl_minutes: int) -> str:
    now = datetime.datetime.utcnow()
    payload = {
        "iss":       "https://api.nonce.dev",
        "sub":       agent_id,
        "spiffe_id": spiffe_id,
        "org":       org,
        "scopes":    scopes,
        "iat":       int(now.timestamp()),
        "exp":       int((now + datetime.timedelta(minutes=ttl_minutes)).timestamp()),
        "jti":       str(uuid.uuid4()),
    }
    return sign_jwt(payload)
