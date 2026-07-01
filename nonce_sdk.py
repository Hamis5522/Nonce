"""
Nonce Python SDK
==================
Official client for the Nonce AI Agent Identity API.

Install:
    pip install nonce   # (or use this file directly)

Usage:
    from nonce_sdk import NonceClient

    client = NonceClient(api_key="nonce_sk_live_...", org="acme-corp")

    # Issue an identity
    agent = client.issue(name="billing-reconciler", scopes=["finance:read"])
    print(agent.spiffe_id)
    print(agent.jwt_token)

    # Verify
    result = client.verify(agent.id)
    print(result.valid)  # True

    # Rotate
    client.rotate(agent.id)

    # Revoke
    client.revoke(agent.id)
"""

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class SVID:
    certificate_pem: str
    jwt_token: str
    serial: str
    not_before: str
    not_after: str
    issuer: str
    key_algorithm: str
    signature_alg: str


@dataclass
class Agent:
    id: str
    name: str
    org: str
    spiffe_id: str
    status: str
    scopes: list
    ttl_minutes: int
    metadata: dict
    issued_at: str
    expires_at: str
    credential_rotations: int
    svid: Optional[SVID] = None
    audit_log: list = field(default_factory=list)

    @property
    def jwt_token(self) -> Optional[str]:
        return self.svid.jwt_token if self.svid else None

    @property
    def certificate_pem(self) -> Optional[str]:
        return self.svid.certificate_pem if self.svid else None

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_revoked(self) -> bool:
        return self.status == "revoked"


@dataclass
class VerifyResult:
    valid: bool
    id: str
    spiffe_id: str
    status: str
    scopes: list
    cert_valid: bool
    jwt_valid: bool
    expires_at: str
    checked_at: str
    reason: Optional[str] = None


@dataclass
class APIKey:
    id: str
    key_prefix: str
    org: str
    name: str
    created_at: str
    last_used: Optional[str] = None
    api_key: Optional[str] = None   # only present at creation


# ── Exceptions ────────────────────────────────────────────────────────────────

class NonceError(Exception):
    def __init__(self, message: str, status_code: int = None, code: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class AgentNotFoundError(NonceError): pass
class AgentRevokedError(NonceError): pass
class DuplicateAgentError(NonceError): pass
class AuthenticationError(NonceError): pass
class RateLimitError(NonceError): pass


# ── Client ────────────────────────────────────────────────────────────────────

class NonceClient:
    """
    Nonce API Client.

    Args:
        api_key:  Your API key (nonce_sk_live_...). Not required in dev mode.
        org:      Your organization slug. Required in dev mode.
        base_url: API base URL. Defaults to http://localhost:8000 for local dev.
        timeout:  Request timeout in seconds. Default 10.
    """

    def __init__(
        self,
        api_key: str = None,
        org: str = None,
        base_url: str = "http://localhost:8000",
        timeout: int = 10,
    ):
        self.api_key  = api_key
        self.org      = org
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout

    # ── Internal request helper ──────────────────────────────────────────────

    def _request(self, method: str, path: str, body: dict = None,
                 params: dict = None) -> dict:
        url = self.base_url + path
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            url += "?" + qs

        data = json.dumps(body).encode() if body else None

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raw = json.loads(e.read())
            code   = raw.get("code", "ERR")
            msg    = raw.get("error", str(e))
            status = e.code
            if status == 401:  raise AuthenticationError(msg, status, code)
            if status == 404:  raise AgentNotFoundError(msg, status, code)
            if status == 409:  raise DuplicateAgentError(msg, status, code)
            if status == 429:  raise RateLimitError(msg, status, code)
            raise NonceError(msg, status, code)

    # ── API Key management ───────────────────────────────────────────────────

    def create_api_key(self, org: str, name: str = "default") -> APIKey:
        """Provision a new API key. The raw key is returned ONCE."""
        data = self._request("POST", "/v1/keys", {"org": org, "name": name})
        return APIKey(
            id=data["id"], key_prefix=data["key_prefix"], org=data["org"],
            name=data["name"], created_at=data["created_at"],
            api_key=data.get("api_key"),
        )

    def list_api_keys(self) -> list:
        params = {"org": self.org} if self.org else {}
        data = self._request("GET", "/v1/keys", params=params)
        return [APIKey(id=k["id"], key_prefix=k["key_prefix"], org=k["org"],
                       name=k["name"], created_at=k["created_at"],
                       last_used=k.get("last_used")) for k in data["api_keys"]]

    # ── Agent identity operations ────────────────────────────────────────────

    def issue(
        self,
        name: str,
        scopes: list = None,
        ttl_minutes: int = 60,
        metadata: dict = None,
    ) -> Agent:
        """
        Issue a new agent identity.

        Args:
            name:        Agent name, e.g. "billing-reconciler"
            scopes:      Permission scopes, e.g. ["finance:read", "ledger:write"]
            ttl_minutes: Credential TTL (1–43200). Default 60.
            metadata:    Arbitrary key-value pairs stored with the agent.

        Returns:
            Agent object with SVID (X.509 cert + JWT) attached.
        """
        body = {
            "name":        name,
            "org":         self.org,
            "scopes":      scopes or [],
            "ttl_minutes": ttl_minutes,
            "metadata":    metadata or {},
        }
        data = self._request("POST", "/v1/agents", body)
        return self._parse_agent(data)

    def get(self, agent_id: str) -> Agent:
        """Fetch a single agent with its audit log."""
        params = {"org": self.org} if self.org else {}
        data = self._request("GET", f"/v1/agents/{agent_id}", params=params)
        return self._parse_agent(data)

    def list(
        self,
        status: str = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple:
        """
        List agents for this org.

        Returns:
            (agents, total_count)
        """
        params = {"limit": limit, "offset": offset}
        if status:   params["status"] = status
        if self.org: params["org"] = self.org
        data = self._request("GET", "/v1/agents", params=params)
        agents = [self._parse_agent(a) for a in data["agents"]]
        return agents, data["total"]

    def verify(self, agent_id: str) -> VerifyResult:
        """
        Verify an agent's identity.
        Validates the X.509 certificate chain and JWT signature + expiry.

        Returns:
            VerifyResult with .valid bool and detail fields.
        """
        params = {"org": self.org} if self.org else {}
        data = self._request("POST", f"/v1/agents/{agent_id}/verify", params=params)
        return VerifyResult(
            valid=data["valid"], id=data["id"], spiffe_id=data["spiffe_id"],
            status=data["status"], scopes=data["scopes"],
            cert_valid=data["cert_valid"], jwt_valid=data["jwt_valid"],
            expires_at=data["expires_at"], checked_at=data["checked_at"],
            reason=data.get("reason"),
        )

    def rotate(self, agent_id: str) -> Agent:
        """
        Rotate credentials for an agent.
        Issues a new X.509 cert + JWT. Old credentials are immediately invalid.

        Returns:
            Updated Agent with new SVID attached under .svid
        """
        params = {"org": self.org} if self.org else {}
        data = self._request("POST", f"/v1/agents/{agent_id}/rotate", params=params)
        agent = self._parse_agent(data)
        # Attach the new_svid explicitly if returned
        if "new_svid" in data:
            agent.svid = SVID(
                certificate_pem=data["new_svid"]["certificate_pem"],
                jwt_token=data["new_svid"]["jwt_token"],
                serial=data["new_svid"]["serial"],
                not_before=data["new_svid"]["not_before"],
                not_after=data["new_svid"]["not_after"],
                issuer="CN=Nonce Root CA, O=Nonce.dev",
                key_algorithm="EC P-256",
                signature_alg="SHA256withECDSA",
            )
        return agent

    def revoke(self, agent_id: str) -> dict:
        """
        Permanently revoke an agent identity.
        The agent will immediately fail all future verify() calls.
        This action cannot be undone.
        """
        params = {"org": self.org} if self.org else {}
        return self._request("DELETE", f"/v1/agents/{agent_id}/revoke", params=params)

    def audit_log(self, agent_id: str, limit: int = 100) -> list:
        """Fetch the full audit trail for an agent."""
        params = {"limit": limit}
        if self.org: params["org"] = self.org
        data = self._request("GET", f"/v1/agents/{agent_id}/audit", params=params)
        return data["events"]

    def ca_cert(self) -> str:
        """Fetch the Nonce CA certificate PEM for client-side verification."""
        data = self._request("GET", "/v1/ca/cert")
        return data["ca_certificate_pem"]

    def health(self) -> dict:
        """Check API health."""
        return self._request("GET", "/health")

    # ── Private helpers ──────────────────────────────────────────────────────

    def _parse_agent(self, data: dict) -> Agent:
        svid = None
        raw_svid = data.get("svid") or data.get("new_svid")
        if raw_svid:
            svid = SVID(
                certificate_pem=raw_svid.get("certificate_pem", ""),
                jwt_token=raw_svid.get("jwt_token", data.get("jwt_token", "")),
                serial=raw_svid.get("serial", data.get("cert_serial", "")),
                not_before=raw_svid.get("not_before", data.get("cert_not_before", "")),
                not_after=raw_svid.get("not_after", data.get("cert_not_after", "")),
                issuer=raw_svid.get("issuer", "CN=Nonce Root CA, O=Nonce.dev"),
                key_algorithm=raw_svid.get("key_algorithm", "EC P-256"),
                signature_alg=raw_svid.get("signature_alg", "SHA256withECDSA"),
            )
        return Agent(
            id=data["id"], name=data["name"], org=data["org"],
            spiffe_id=data["spiffe_id"], status=data["status"],
            scopes=data.get("scopes", []), ttl_minutes=data.get("ttl_minutes", 60),
            metadata=data.get("metadata", {}), issued_at=data.get("issued_at", ""),
            expires_at=data.get("expires_at", ""),
            credential_rotations=data.get("credential_rotations", 0),
            svid=svid,
            audit_log=data.get("audit_log", []),
        )
