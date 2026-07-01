#!/usr/bin/env python3
"""
AgentID SDK Integration Tests + Usage Examples
Runs against a live server at localhost:8000
Start the server first: python3 server.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nonce_sdk import NonceClient, NonceError, AgentNotFoundError, DuplicateAgentError

GREEN = "\033[32m"; RED = "\033[31m"; CYAN = "\033[36m"
YELLOW = "\033[33m"; NC = "\033[0m"; BOLD = "\033[1m"

passed = 0; failed = 0

def check(label, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  {GREEN}✓{NC} {label}")
        passed += 1
    else:
        print(f"  {RED}✗{NC} {label}  {detail}")
        failed += 1

def hr(title):
    print(f"\n{CYAN}── {title} {'─' * (44 - len(title))}{NC}")

client = NonceClient(org="sdk-test-org")

# ── Health ────────────────────────────────────────────────────────────────────
hr("Health Check")
try:
    h = client.health()
    check("API is operational",        h["status"] == "operational")
    check("Database service OK",       h["services"]["database"] == "ok")
    check("CA service OK",             h["services"]["ca"] == "ok")
    check("JWT signing OK",            h["services"]["jwt_signing"] == "ok")
except Exception as e:
    print(f"  {RED}✗ Cannot connect to server: {e}{NC}")
    print(f"  {YELLOW}Start the server first: python3 server.py{NC}")
    sys.exit(1)

# ── CA Certificate ────────────────────────────────────────────────────────────
hr("CA Certificate")
ca = client.ca_cert()
check("CA cert is valid PEM",   "BEGIN CERTIFICATE" in ca)
check("CA cert has content",    len(ca) > 400)

# ── Issue Identity ────────────────────────────────────────────────────────────
hr("Issue Agent Identity")
agent = client.issue(
    name="billing-reconciler",
    scopes=["finance:read", "ledger:write"],
    ttl_minutes=60,
    metadata={"team": "finops", "env": "production"},
)
check("Agent ID issued",            agent.id.startswith("agt_"))
check("SPIFFE ID is correct format", agent.spiffe_id.startswith("spiffe://"))
check("SPIFFE ID contains org",      "sdk-test-org" in agent.spiffe_id)
check("SPIFFE ID contains name",     "billing-reconciler" in agent.spiffe_id)
check("Status is active",            agent.is_active)
check("Scopes stored correctly",     "finance:read" in agent.scopes)
check("Metadata stored",             agent.metadata.get("team") == "finops")
check("SVID attached",               agent.svid is not None)
check("Certificate PEM present",     "BEGIN CERTIFICATE" in (agent.certificate_pem or ""))
check("JWT token present",           (agent.jwt_token or "").startswith("eyJ"))
check("TTL is 60 minutes",           agent.ttl_minutes == 60)
check("Expires at is set",           len(agent.expires_at) > 10)

print(f"\n  {YELLOW}Agent ID:  {NC}{agent.id}")
print(f"  {YELLOW}SPIFFE ID: {NC}{agent.spiffe_id}")
print(f"  {YELLOW}Expires:   {NC}{agent.expires_at}")

# Issue second agent
agent2 = client.issue(
    name="payments-processor",
    scopes=["payments:execute", "users:read"],
    ttl_minutes=30,
)
check("Second agent issued",        agent2.id.startswith("agt_"))
check("Second agent different ID",  agent2.id != agent.id)

# Issue third agent for revocation test
agent3 = client.issue(name="temp-scraper", scopes=["data:read"], ttl_minutes=5)
check("Third agent issued",         agent3.id.startswith("agt_"))

# ── Duplicate detection ───────────────────────────────────────────────────────
hr("Duplicate Detection")
try:
    client.issue(name="billing-reconciler", scopes=["finance:read"])
    check("Duplicate blocked", False, "should have raised DuplicateAgentError")
except DuplicateAgentError:
    check("Duplicate correctly blocked", True)
except Exception as e:
    check("Duplicate blocked", False, str(e))

# ── Get Agent ─────────────────────────────────────────────────────────────────
hr("Get Agent")
fetched = client.get(agent.id)
check("Agent fetched by ID",        fetched.id == agent.id)
check("Name correct",               fetched.name == "billing-reconciler")
check("Scopes deserialized",        isinstance(fetched.scopes, list))
check("Audit log attached",         len(fetched.audit_log) >= 1)
check("identity_issued in log",     any(e["event"] == "identity_issued" for e in fetched.audit_log))

try:
    client.get("agt_doesnotexist")
    check("Not found raises error", False)
except AgentNotFoundError:
    check("Not found correctly raises AgentNotFoundError", True)

# ── List Agents ───────────────────────────────────────────────────────────────
hr("List Agents")
agents, total = client.list()
check("Returns list",          isinstance(agents, list))
check("Total >= 3",            total >= 3)
check("All agents in org",     all(a.org == "sdk-test-org" for a in agents))

active_agents, active_total = client.list(status="active")
check("Active filter works",   all(a.is_active for a in active_agents))
check("Active count >= 3",     active_total >= 3)

paginated, _ = client.list(limit=1, offset=0)
check("Pagination limit=1",    len(paginated) == 1)

# ── Verify ────────────────────────────────────────────────────────────────────
hr("Verify Identity")
result = client.verify(agent.id)
check("Verification returns result",  result is not None)
check("valid=True for active agent",  result.valid == True)
check("cert_valid=True",              result.cert_valid == True)
check("jwt_valid=True",               result.jwt_valid == True)
check("scopes present in result",     "finance:read" in result.scopes)
check("spiffe_id in result",          "billing-reconciler" in result.spiffe_id)
check("checked_at timestamp set",     len(result.checked_at) > 10)
check("reason is None for valid",     result.reason is None)

# ── Rotate Credentials ────────────────────────────────────────────────────────
hr("Rotate Credentials")
old_serial = fetched.cert_serial if hasattr(fetched, "cert_serial") else ""

rotated = client.rotate(agent.id)
check("Rotate returns updated agent",   rotated.id == agent.id)
check("Rotation count incremented",     rotated.credential_rotations >= 1)
check("New SVID attached",              rotated.svid is not None)
check("New cert is valid PEM",          "BEGIN CERTIFICATE" in (rotated.certificate_pem or ""))
check("New JWT present",                (rotated.jwt_token or "").startswith("eyJ"))

# Verify still valid after rotation
result2 = client.verify(agent.id)
check("Still valid after rotation",     result2.valid == True)

# Verify rotation in audit log
log = client.audit_log(agent.id)
check("Rotation logged in audit trail", any(e["event"] == "credential_rotated" for e in log))
check("Verification logged",            any("verification" in e["event"] for e in log))

# ── Audit Log ─────────────────────────────────────────────────────────────────
hr("Audit Log")
log = client.audit_log(agent.id)
check("Log has multiple events",       len(log) >= 3)
check("Events have timestamps",        all("ts" in e for e in log))
check("Events have event field",       all("event" in e for e in log))
check("Log is newest-first",           log[0]["ts"] >= log[-1]["ts"])

limited_log = client.audit_log(agent.id, limit=1)
check("Limit param works",             len(limited_log) == 1)

# ── Revoke ────────────────────────────────────────────────────────────────────
hr("Revoke Identity")
result_r = client.revoke(agent3.id)
check("Revoke returns message",        "revoked" in result_r.get("message", "").lower())
check("revoked_at timestamp present",  "revoked_at" in result_r)

# Verify revoked agent
revoked_check = client.verify(agent3.id)
check("Revoked agent: valid=False",    revoked_check.valid == False)
check("Revoked agent: reason set",     revoked_check.reason == "identity_revoked")

# Can't rotate a revoked agent
try:
    client.rotate(agent3.id)
    check("Rotate revoked raises error", False)
except NonceError as e:
    check("Rotate revoked correctly raises NonceError", True)

# Revoke already-revoked
try:
    client.revoke(agent3.id)
    check("Double-revoke raises error", False)
except NonceError as e:
    check("Double-revoke correctly blocked", True)

# ── Cross-org isolation ───────────────────────────────────────────────────────
hr("Org Isolation")
other_client = NonceClient(org="other-org")
other_agents, other_total = other_client.list()
check("Other org sees 0 agents",   other_total == 0)

try:
    other_client.get(agent.id)
    check("Cross-org access blocked", False)
except AgentNotFoundError:
    check("Cross-org access correctly blocked", True)

# ── Summary ───────────────────────────────────────────────────────────────────
total_tests = passed + failed
print(f"""
{BOLD}{'─' * 52}{NC}
  {BOLD}SDK Test Results: {GREEN}{passed} passed{NC}, {RED}{failed} failed{NC} / {total_tests} total
{'─' * 52}""")

if failed == 0:
    print(f"  {GREEN}{BOLD}All {total_tests} tests passed ✓{NC}\n")
else:
    print(f"  {RED}{BOLD}{failed} test(s) failed ✗{NC}\n")
    sys.exit(1)
