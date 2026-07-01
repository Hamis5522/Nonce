#!/usr/bin/env python3
"""
Nonce Backend Server
Production-grade HTTP API for AI Agent Identity Infrastructure.

Endpoints:
  POST   /v1/keys                    — Provision an API key
  GET    /v1/keys                    — List API keys for org
  POST   /v1/agents                  — Issue agent identity (SVID + JWT)
  GET    /v1/agents                  — List agents
  GET    /v1/agents/:id              — Get agent detail
  POST   /v1/agents/:id/verify       — Verify agent identity
  POST   /v1/agents/:id/rotate       — Rotate credentials
  DELETE /v1/agents/:id/revoke       — Revoke identity
  GET    /v1/agents/:id/audit        — Audit log
  GET    /v1/ca/cert                 — Fetch CA certificate (public)
  GET    /health                     — Health check

Auth: Bearer token in Authorization header (API key or skip with dev mode)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import uuid
import datetime
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

from ca.certificate_authority import issue_svid, verify_svid_cert, get_ca_cert_pem
from db.database import (
    init_db, create_agent, get_agent, get_agent_by_spiffe, list_agents,
    update_agent_svid, revoke_agent, append_audit, get_audit_log,
    create_api_key, get_api_key_by_hash, touch_api_key, list_api_keys,
)
from middleware.auth import (
    generate_api_key, hash_api_key, build_agent_jwt, verify_jwt,
)

# ── Config ────────────────────────────────────────────────────────────────────
PORT       = int(os.environ.get("PORT", 8000))
DEV_MODE   = os.environ.get("NONCE_DEV", "true").lower() == "true"
DEV_ORG    = "dev-org"

# Rate limiting: max requests per minute per IP
RATE_LIMIT  = 120
_rate_store = defaultdict(list)

# ── Helpers ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"

def make_spiffe_id(org: str, name: str) -> str:
    slug = name.lower().replace(" ", "-")
    return f"spiffe://{org}.nonce.dev/agent/{slug}"

def sanitize_agent(agent: dict, include_keys: bool = False) -> dict:
    """Strip private key from API responses unless explicitly requested."""
    out = {k: v for k, v in agent.items() if k != "private_key_pem"}
    if not include_keys:
        out.pop("private_key_pem", None)
    return out

def is_rate_limited(ip: str) -> bool:
    now = time.time()
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < 60]
    if len(_rate_store[ip]) >= RATE_LIMIT:
        return True
    _rate_store[ip].append(now)
    return False

# ── Request Handler ───────────────────────────────────────────────────────────

class NonceHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        ts = datetime.datetime.utcnow().strftime("%H:%M:%S")
        method = getattr(self, '_method', '?')
        path   = getattr(self, '_path',   '?')
        status = args[1] if len(args) > 1 else '?'
        color  = "\033[32m" if str(status).startswith('2') else "\033[31m"
        print(f"\033[90m{ts}\033[0m {color}{status}\033[0m {method} {path}")

    def _parse_request(self):
        parsed   = urlparse(self.path)
        self._path    = parsed.path.rstrip("/")
        self._method  = self.command
        self._query   = parse_qs(parsed.query)

        # Read body
        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length) if length else b"{}"
        try:
            self._body = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            self._body = {}

    def _get_org(self) -> "str | None":
        """Authenticate request. Returns org string or None."""
        # Always check Authorization header first
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            raw_key  = auth[7:]
            key_hash = hash_api_key(raw_key)
            key_rec  = get_api_key_by_hash(key_hash)
            if key_rec:
                touch_api_key(key_rec["id"])
                return key_rec["org"]

        if DEV_MODE:
            return (
                self._body.get("org")
                or self._query.get("org", [None])[0]
                or DEV_ORG
            )

        return None

    def _respond(self, status: int, data: dict):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type",                  "application/json")
        self.send_header("Content-Length",                str(len(body)))
        self.send_header("Access-Control-Allow-Origin",   "*")
        self.send_header("Access-Control-Allow-Headers",  "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods",  "GET, POST, DELETE, OPTIONS")
        self.send_header("X-Nonce-Version",             "1.0.0")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, status: int, msg: str, code: str = None):
        self._respond(status, {
            "error":   msg,
            "code":    code or f"ERR_{status}",
            "status":  status,
        })

    def do_OPTIONS(self):
        self._parse_request()
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()

    def do_GET(self):
        self._parse_request()
        self._route()

    def do_POST(self):
        self._parse_request()
        self._route()

    def do_DELETE(self):
        self._parse_request()
        self._route()

    def _route(self):
        ip = self.client_address[0]
        if is_rate_limited(ip):
            return self._err(429, "Rate limit exceeded", "RATE_LIMITED")

        path = self._path
        method = self._method

        # ── Public endpoints ──────────────────────────────────────────────────
        if path == "/health" and method == "GET":
            return self._health()

        if path == "/v1/ca/cert" and method == "GET":
            return self._respond(200, {
                "ca_certificate_pem": get_ca_cert_pem(),
                "trust_domain": "nonce.dev",
                "algorithm":    "EC P-256",
            })

        # ── API key provisioning ──────────────────────────────────────────────
        if path == "/v1/keys" and method == "POST":
            return self._create_api_key()

        # ── Auth gate ─────────────────────────────────────────────────────────
        org = self._get_org()
        if not org:
            return self._err(401, "Missing or invalid API key", "UNAUTHORIZED")

        if path == "/v1/keys" and method == "GET":
            return self._list_api_keys(org)

        # ── Agent routes ──────────────────────────────────────────────────────
        if path == "/v1/agents" and method == "POST":
            return self._issue_agent(org)

        if path == "/v1/agents" and method == "GET":
            return self._list_agents(org)

        # /v1/agents/:id  and sub-routes
        parts = path.split("/")
        if len(parts) >= 4 and parts[1] == "v1" and parts[2] == "agents":
            agent_id = parts[3]

            if len(parts) == 4:
                if method == "GET":
                    return self._get_agent(org, agent_id)

            if len(parts) == 5:
                action = parts[4]
                if action == "verify" and method == "POST":
                    return self._verify_agent(org, agent_id)
                if action == "rotate" and method == "POST":
                    return self._rotate_agent(org, agent_id)
                if action == "revoke" and method == "DELETE":
                    return self._revoke_agent(org, agent_id)
                if action == "audit" and method == "GET":
                    return self._get_audit(org, agent_id)

        self._err(404, f"Unknown endpoint: {method} {path}", "NOT_FOUND")

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _health(self):
        self._respond(200, {
            "status":    "operational",
            "version":   "1.0.0",
            "timestamp": now_iso(),
            "services": {
                "database":    "ok",
                "ca":          "ok",
                "jwt_signing": "ok",
            },
        })

    def _create_api_key(self):
        org  = self._body.get("org")
        name = self._body.get("name", "default")
        if not org:
            return self._err(400, "org is required", "MISSING_ORG")

        raw_key, key_hash, key_prefix = generate_api_key()
        key_id = "kid_" + str(uuid.uuid4()).replace("-", "")[:16]
        create_api_key(key_id, key_hash, key_prefix, org, name)

        self._respond(201, {
            "id":         key_id,
            "api_key":    raw_key,   # shown ONCE
            "key_prefix": key_prefix,
            "org":        org,
            "name":       name,
            "created_at": now_iso(),
            "warning":    "Store this key securely — it will not be shown again.",
        })

    def _list_api_keys(self, org: str):
        keys = list_api_keys(org)
        self._respond(200, {"api_keys": keys, "count": len(keys)})

    def _issue_agent(self, org: str):
        b = self._body
        name = b.get("name")
        if not name:
            return self._err(400, "name is required", "MISSING_NAME")

        scopes      = b.get("scopes", [])
        ttl_minutes = int(b.get("ttl_minutes", 60))
        metadata    = b.get("metadata", {})

        if ttl_minutes < 1 or ttl_minutes > 43200:   # max 30 days
            return self._err(400, "ttl_minutes must be 1–43200", "INVALID_TTL")

        agent_id  = "agt_" + str(uuid.uuid4()).replace("-", "")[:20]
        spiffe_id = make_spiffe_id(org, name)

        # Check duplicate
        existing = get_agent_by_spiffe(spiffe_id)
        if existing and existing.get("org") == org and existing.get("status") == "active":
            return self._err(409, f"Active agent '{name}' already exists for org '{org}'", "DUPLICATE_AGENT")

        # Issue real SVID
        svid = issue_svid(spiffe_id, ttl_minutes)

        # Sign JWT
        jwt_token = build_agent_jwt(agent_id, spiffe_id, org, scopes, ttl_minutes)

        issued_at  = now_iso()
        expires_at = svid["not_after"]

        agent = {
            "id":                   agent_id,
            "name":                 name,
            "org":                  org,
            "spiffe_id":            spiffe_id,
            "status":               "active",
            "scopes":               scopes,
            "ttl_minutes":          ttl_minutes,
            "metadata":             metadata,
            "issued_at":            issued_at,
            "expires_at":           expires_at,
            "credential_rotations": 0,
            "certificate_pem":      svid["certificate_pem"],
            "private_key_pem":      svid["private_key_pem"],
            "jwt_token":            jwt_token,
            "cert_serial":          svid["serial"],
            "cert_not_before":      svid["not_before"],
            "cert_not_after":       svid["not_after"],
        }

        create_agent(agent)
        append_audit(agent_id, "identity_issued", meta={"scopes": scopes, "ttl_minutes": ttl_minutes})

        response = sanitize_agent(agent)
        response["svid"] = {
            "certificate_pem": svid["certificate_pem"],
            "jwt_token":       jwt_token,
            "serial":          svid["serial"],
            "not_before":      svid["not_before"],
            "not_after":       svid["not_after"],
            "issuer":          svid["issuer"],
            "key_algorithm":   svid["key_algorithm"],
            "signature_alg":   svid["signature_alg"],
        }
        self._respond(201, response)

    def _list_agents(self, org: str):
        status = self._query.get("status", [None])[0]
        limit  = min(int(self._query.get("limit",  [50])[0]), 200)
        offset = int(self._query.get("offset", [0])[0])
        agents, total = list_agents(org, status, limit, offset)
        self._respond(200, {
            "agents": [sanitize_agent(a) for a in agents],
            "total":  total,
            "limit":  limit,
            "offset": offset,
        })

    def _get_agent(self, org: str, agent_id: str):
        agent = get_agent(agent_id, org)
        if not agent:
            return self._err(404, "Agent not found", "NOT_FOUND")
        resp = sanitize_agent(agent)
        resp["audit_log"] = get_audit_log(agent_id, limit=20)
        self._respond(200, resp)

    def _verify_agent(self, org: str, agent_id: str):
        agent = get_agent(agent_id, org)
        if not agent:
            return self._err(404, "Agent not found", "NOT_FOUND")

        # Check status
        if agent["status"] == "revoked":
            append_audit(agent_id, "verification_failed", meta={"reason": "revoked"})
            return self._respond(200, {
                "valid":      False,
                "reason":     "identity_revoked",
                "id":         agent_id,
                "spiffe_id":  agent["spiffe_id"],
                "status":     "revoked",
                "scopes":     agent.get("scopes", []),
                "expires_at": agent.get("expires_at", ""),
                "cert_valid": False,
                "jwt_valid":  False,
                "checked_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            })

        # Verify X.509 cert against CA
        cert_result = verify_svid_cert(agent["certificate_pem"])

        # Verify JWT
        jwt_payload = verify_jwt(agent["jwt_token"])
        jwt_valid   = jwt_payload is not None

        valid = cert_result["valid"] and jwt_valid

        reason = None
        if not cert_result["valid"]:
            reason = cert_result["reason"]
        elif not jwt_valid:
            reason = "jwt_expired_or_invalid"

        event = "verification_passed" if valid else "verification_failed"
        append_audit(agent_id, event, meta={"reason": reason})

        self._respond(200, {
            "valid":      valid,
            "id":         agent_id,
            "spiffe_id":  agent["spiffe_id"],
            "org":        agent["org"],
            "status":     agent["status"],
            "scopes":     agent["scopes"],
            "expires_at": agent["expires_at"],
            "cert_valid": cert_result["valid"],
            "jwt_valid":  jwt_valid,
            "reason":     reason,
            "checked_at": now_iso(),
        })

    def _rotate_agent(self, org: str, agent_id: str):
        agent = get_agent(agent_id, org)
        if not agent:
            return self._err(404, "Agent not found", "NOT_FOUND")
        if agent["status"] == "revoked":
            return self._err(400, "Cannot rotate credentials for a revoked agent", "REVOKED")

        # Issue new SVID
        new_svid      = issue_svid(agent["spiffe_id"], agent["ttl_minutes"])
        new_jwt       = build_agent_jwt(
            agent_id, agent["spiffe_id"], org,
            agent["scopes"], agent["ttl_minutes"]
        )
        new_expires   = new_svid["not_after"]

        update_agent_svid(agent_id, new_svid, new_jwt, new_expires)
        append_audit(agent_id, "credential_rotated", meta={"new_serial": new_svid["serial"]})

        # Fetch updated record
        updated = get_agent(agent_id, org)
        resp = sanitize_agent(updated)
        resp["new_svid"] = {
            "certificate_pem": new_svid["certificate_pem"],
            "jwt_token":       new_jwt,
            "serial":          new_svid["serial"],
            "not_before":      new_svid["not_before"],
            "not_after":       new_svid["not_after"],
        }
        self._respond(200, resp)

    def _revoke_agent(self, org: str, agent_id: str):
        agent = get_agent(agent_id, org)
        if not agent:
            return self._err(404, "Agent not found", "NOT_FOUND")
        if agent["status"] == "revoked":
            return self._err(400, "Agent already revoked", "ALREADY_REVOKED")

        revoke_agent(agent_id)
        append_audit(agent_id, "identity_revoked")
        self._respond(200, {
            "message":   "Identity permanently revoked",
            "id":        agent_id,
            "spiffe_id": agent["spiffe_id"],
            "revoked_at": now_iso(),
        })

    def _get_audit(self, org: str, agent_id: str):
        agent = get_agent(agent_id, org)
        if not agent:
            return self._err(404, "Agent not found", "NOT_FOUND")
        limit  = min(int(self._query.get("limit", [100])[0]), 500)
        events = get_audit_log(agent_id, limit)
        self._respond(200, {
            "agent_id": agent_id,
            "events":   events,
            "count":    len(events),
        })


# ── Startup ───────────────────────────────────────────────────────────────────

def main():
    init_db()
    print("\033[1m")
    print("  █████╗  ██████╗ ███████╗███╗  ██╗████████╗██╗██████╗ ")
    print(" ██╔══██╗██╔════╝ ██╔════╝████╗ ██║╚══██╔══╝██║██╔══██╗")
    print(" ███████║██║  ███╗█████╗  ██╔██╗██║   ██║   ██║██║  ██║")
    print(" ██╔══██║██║   ██║██╔══╝  ██║╚████║   ██║   ██║██║  ██║")
    print(" ██║  ██║╚██████╔╝███████╗██║ ╚███║   ██║   ██║██████╔╝")
    print(" ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚══╝   ╚═╝   ╚═╝╚═════╝ ")
    print("\033[0m")
    print(f"\033[36m  AI Agent Identity Infrastructure\033[0m  v1.0.0")
    print(f"\033[90m  ─────────────────────────────────────────────────\033[0m")
    print(f"  \033[32m●\033[0m Server:       http://localhost:{PORT}")
    print(f"  \033[32m●\033[0m Mode:         {'DEV (no auth required)' if DEV_MODE else 'PRODUCTION'}")
    print(f"  \033[32m●\033[0m Database:     {os.path.abspath('db/nonce.db')}")
    print(f"  \033[32m●\033[0m CA cert:      {os.path.abspath('ca/ca_cert.pem')}")
    print(f"\033[90m  ─────────────────────────────────────────────────\033[0m\n")

    server = HTTPServer(("0.0.0.0", PORT), NonceHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\033[33m  Server stopped.\033[0m")


if __name__ == "__main__":
    main()
