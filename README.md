# ⬡ Nonce — AI Agent Identity Infrastructure

**The Auth0 for AI agents.** Issue, verify, rotate, and revoke cryptographic identities for AI agents — SPIFFE-compliant, short-lived, zero-trust.

---

## What This Is

Every AI agent your company deploys needs a cryptographic identity to:
- Prove **who it is** to other systems (not just "some AI")
- Carry **scoped permissions** (what it's allowed to do)
- Leave an **auditable trail** of every action
- Have credentials that **auto-expire and rotate** (zero-trust)
- Be **instantly revocable** if compromised

Nonce is the infrastructure layer that provides all of this in 5 lines of code.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Nonce API v1                           │
├────────────────┬────────────────┬───────────────────────────┤
│  Certificate   │   JWT Engine   │    Audit Logger           │
│  Authority     │   (HS-256)     │    (SQLite WAL)           │
│  (EC P-256)    │                │                           │
├────────────────┴────────────────┴───────────────────────────┤
│              SPIFFE/SVID Identity Layer                     │
│   spiffe://{org}.nonce.dev/agent/{name}                   │
└─────────────────────────────────────────────────────────────┘
```

Each agent gets a **SPIFFE SVID** — a SPIFFE Verifiable Identity Document containing:
- An **X.509 certificate** (EC P-256) signed by the Nonce CA, with the SPIFFE URI in the SAN
- A **JWT** with scopes, org, expiry, and agent ID
- A **TTL** (1 min to 30 days) — credentials auto-expire

---

## Quickstart

### 1. Run locally (dev mode — no auth required)

```bash
pip install cryptography PyJWT
python3 server.py
# Server at http://localhost:8000
```

### 2. Run with Docker

```bash
# Generate a JWT secret
echo "NONCE_JWT_SECRET=$(openssl rand -hex 32)" > .env

docker compose up -d
```

### 3. Issue your first agent identity

```bash
curl -X POST http://localhost:8000/v1/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "billing-reconciler",
    "org":  "acme-corp",
    "scopes": ["finance:read", "ledger:write"],
    "ttl_minutes": 60
  }'
```

Response:
```json
{
  "id": "agt_a1b2c3d4e5f6...",
  "spiffe_id": "spiffe://acme-corp.nonce.dev/agent/billing-reconciler",
  "status": "active",
  "svid": {
    "certificate_pem": "-----BEGIN CERTIFICATE-----\n...",
    "jwt_token": "eyJhbGciOiJIUzI1NiJ9...",
    "serial": "3A:B1:9C:...",
    "not_before": "2026-06-12T10:00:00Z",
    "not_after":  "2026-06-12T11:00:00Z",
    "key_algorithm": "EC P-256",
    "signature_alg": "SHA256withECDSA"
  },
  "scopes": ["finance:read", "ledger:write"],
  "issued_at": "2026-06-12T10:00:00Z",
  "expires_at": "2026-06-12T11:00:00Z"
}
```

---

## API Reference

### Authentication (Production)

All endpoints (except `/health` and `/v1/ca/cert`) require:
```
Authorization: Bearer nonce_sk_live_<your_key>
```

Provision a key:
```bash
curl -X POST http://localhost:8000/v1/keys \
  -d '{"org": "acme-corp", "name": "production"}'
```

> **Security:** API keys are stored as SHA-256 hashes. The raw key is shown once and never stored.

---

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Health check (public) |
| `GET`  | `/v1/ca/cert` | Fetch CA certificate (public) |
| `POST` | `/v1/keys` | Provision API key |
| `GET`  | `/v1/keys` | List API keys for org |
| `POST` | `/v1/agents` | Issue agent identity |
| `GET`  | `/v1/agents` | List agents (`?status=active&limit=50`) |
| `GET`  | `/v1/agents/:id` | Get agent + audit log |
| `POST` | `/v1/agents/:id/verify` | Verify identity (cert + JWT) |
| `POST` | `/v1/agents/:id/rotate` | Rotate credentials |
| `DELETE`| `/v1/agents/:id/revoke` | Permanently revoke |
| `GET`  | `/v1/agents/:id/audit` | Full audit trail |

---

### POST /v1/agents — Issue Identity

**Request:**
```json
{
  "name":        "payments-processor",
  "org":         "acme-corp",
  "scopes":      ["payments:execute", "users:read"],
  "ttl_minutes": 30,
  "metadata":    {"team": "payments", "env": "production"}
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | ✅ | Agent name (becomes slug in SPIFFE ID) |
| `org`  | ✅ | Organization (dev mode only — from API key in prod) |
| `scopes` | — | Permission scopes (free-form strings) |
| `ttl_minutes` | — | Credential TTL, 1–43200 (default: 60) |
| `metadata` | — | Arbitrary key-value pairs |

---

### POST /v1/agents/:id/verify

Returns a full verification result including cert chain validation and JWT check:

```json
{
  "valid":      true,
  "id":         "agt_...",
  "spiffe_id":  "spiffe://acme-corp.nonce.dev/agent/payments-processor",
  "scopes":     ["payments:execute", "users:read"],
  "cert_valid": true,
  "jwt_valid":  true,
  "expires_at": "2026-06-12T11:00:00Z",
  "checked_at": "2026-06-12T10:30:00Z"
}
```

---

### POST /v1/agents/:id/rotate

Issues fresh X.509 + JWT credentials without downtime. The agent ID stays the same. Old credentials are immediately invalid.

```json
{
  "credential_rotations": 3,
  "new_svid": {
    "certificate_pem": "-----BEGIN CERTIFICATE-----\n...",
    "jwt_token":       "eyJ...",
    "serial":          "9F:2A:...",
    "not_after":       "2026-06-12T12:00:00Z"
  }
}
```

---

## Security Design

### Zero-Trust Principles
- **Short-lived credentials**: Default TTL is 60 minutes. Agents must rotate regularly.
- **Scoped permissions**: Each agent carries only the scopes it was issued with.
- **Instant revocation**: Revoked agents fail verification immediately.
- **Tamper detection**: X.509 certificates are cryptographically signed by the CA. Any modification fails ECDSA verification.

### Key Storage
- CA private key: stored in `/data/ca/ca_key.pem` — **mount this as a secret in production**
- API keys: stored as **SHA-256 hashes only** — raw key shown once
- Agent private keys: stored in DB for retrieval — consider encrypting at rest in production

### Production Hardening Checklist
- [ ] Set `NONCE_DEV=false`
- [ ] Set `NONCE_JWT_SECRET` to a 256-bit random value
- [ ] Mount `/data/ca` as a Kubernetes secret or AWS Secrets Manager volume
- [ ] Enable TLS termination via nginx/Caddy in front of this server
- [ ] Set up DB backups for `/data/db/nonce.db`
- [ ] Add rate limiting at the load balancer layer
- [ ] Rotate the CA certificate annually

---

## Project Structure

```
nonce-backend/
├── server.py                  # Main HTTP server & routing
├── ca/
│   ├── certificate_authority.py   # X.509 CA, SVID issuance & verification
│   ├── ca_key.pem             # CA private key (auto-generated on first run)
│   └── ca_cert.pem            # CA certificate (distribute to clients)
├── db/
│   ├── database.py            # SQLite ORM layer
│   └── nonce.db             # SQLite database (auto-created)
├── middleware/
│   └── auth.py                # API key hashing, JWT signing/verification
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Roadmap to Production

### v1.1 — Hardening
- [ ] mTLS between agents and API
- [ ] JWKS endpoint (`/v1/.well-known/jwks.json`) for RS256 JWTs
- [ ] Webhook notifications on revocation events
- [ ] PostgreSQL support for horizontal scaling

### v1.2 — Developer Experience  
- [ ] Python SDK (`pip install nonce`)
- [ ] Node.js SDK (`npm install @nonce/sdk`)
- [ ] Terraform provider
- [ ] GitHub Actions integration

### v2.0 — Platform
- [ ] Telecom layer (real phone numbers for agents via GSMA Open Gateway)
- [ ] Agent-to-agent trust chains (delegation)
- [ ] OpenFGA authorization engine integration
- [ ] Multi-tenant web dashboard

---

## Why Nonce vs. Existing Tools

| Feature | Nonce | Okta/Auth0 | AWS IAM | SPIRE |
|---------|---------|-----------|---------|-------|
| Built for AI agents | ✅ | ❌ | ❌ | Partial |
| 5-line integration | ✅ | ❌ | ❌ | ❌ |
| Real SPIFFE SVIDs | ✅ | ❌ | ❌ | ✅ |
| Developer-first pricing | ✅ | ❌ | ❌ | OSS only |
| Telecom identity layer | Roadmap | ❌ | ❌ | ❌ |
| Sub-10ms issuance | ✅ | ❌ | ❌ | ✅ |

---

## License

MIT — use freely, build on top of it, make money with it.

---

*Built with Python 3.12 · EC P-256 · SPIFFE/SVID · SQLite · Zero external dependencies in production*
