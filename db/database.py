"""
Nonce Database Layer
SQLite-backed persistence for agents, API keys, and audit events.
"""

import sqlite3
import os
import json
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "nonce.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id          TEXT PRIMARY KEY,
            key_hash    TEXT UNIQUE NOT NULL,
            key_prefix  TEXT NOT NULL,
            org         TEXT NOT NULL,
            name        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            last_used   TEXT,
            revoked     INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS agents (
            id                   TEXT PRIMARY KEY,
            name                 TEXT NOT NULL,
            org                  TEXT NOT NULL,
            spiffe_id            TEXT UNIQUE NOT NULL,
            status               TEXT DEFAULT 'active',
            scopes               TEXT NOT NULL,
            ttl_minutes          INTEGER NOT NULL,
            metadata             TEXT DEFAULT '{}',
            issued_at            TEXT NOT NULL,
            expires_at           TEXT NOT NULL,
            credential_rotations INTEGER DEFAULT 0,
            certificate_pem      TEXT,
            private_key_pem      TEXT,
            jwt_token            TEXT,
            cert_serial          TEXT,
            cert_not_before      TEXT,
            cert_not_after       TEXT,
            api_key_id           TEXT REFERENCES api_keys(id)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id   TEXT NOT NULL,
            event      TEXT NOT NULL,
            actor      TEXT DEFAULT 'api',
            meta       TEXT DEFAULT '{}',
            ts         TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_agents_org    ON agents(org);
        CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
        CREATE INDEX IF NOT EXISTS idx_audit_agent   ON audit_log(agent_id);
        CREATE INDEX IF NOT EXISTS idx_apikeys_hash  ON api_keys(key_hash);
    """)
    conn.commit()
    conn.close()


# ── API Key operations ────────────────────────────────────────────────────────

def create_api_key(key_id, key_hash, key_prefix, org, name):
    now = datetime.datetime.utcnow().isoformat() + "Z"
    conn = get_conn()
    conn.execute(
        "INSERT INTO api_keys (id, key_hash, key_prefix, org, name, created_at) VALUES (?,?,?,?,?,?)",
        (key_id, key_hash, key_prefix, org, name, now)
    )
    conn.commit()
    conn.close()


def get_api_key_by_hash(key_hash):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM api_keys WHERE key_hash = ? AND revoked = 0", (key_hash,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def touch_api_key(key_id):
    now = datetime.datetime.utcnow().isoformat() + "Z"
    conn = get_conn()
    conn.execute("UPDATE api_keys SET last_used = ? WHERE id = ?", (now, key_id))
    conn.commit()
    conn.close()


def list_api_keys(org):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, key_prefix, org, name, created_at, last_used, revoked FROM api_keys WHERE org = ?",
        (org,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Agent operations ──────────────────────────────────────────────────────────

def create_agent(agent: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO agents (
            id, name, org, spiffe_id, status, scopes, ttl_minutes,
            metadata, issued_at, expires_at, credential_rotations,
            certificate_pem, private_key_pem, jwt_token,
            cert_serial, cert_not_before, cert_not_after, api_key_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        agent["id"], agent["name"], agent["org"], agent["spiffe_id"],
        agent.get("status", "active"),
        json.dumps(agent.get("scopes", [])),
        agent["ttl_minutes"],
        json.dumps(agent.get("metadata", {})),
        agent["issued_at"], agent["expires_at"],
        agent.get("credential_rotations", 0),
        agent.get("certificate_pem"), agent.get("private_key_pem"),
        agent.get("jwt_token"), agent.get("cert_serial"),
        agent.get("cert_not_before"), agent.get("cert_not_after"),
        agent.get("api_key_id"),
    ))
    conn.commit()
    conn.close()


def get_agent(agent_id: str, org: str = None):
    conn = get_conn()
    if org:
        row = conn.execute(
            "SELECT * FROM agents WHERE id = ? AND org = ?", (agent_id, org)
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    conn.close()
    return _agent_row_to_dict(row) if row else None


def list_agents(org: str, status: str = None, limit: int = 100, offset: int = 0):
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM agents WHERE org = ? AND status = ? ORDER BY issued_at DESC LIMIT ? OFFSET ?",
            (org, status, limit, offset)
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE org = ? AND status = ?", (org, status)
        ).fetchone()[0]
    else:
        rows = conn.execute(
            "SELECT * FROM agents WHERE org = ? ORDER BY issued_at DESC LIMIT ? OFFSET ?",
            (org, limit, offset)
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE org = ?", (org,)
        ).fetchone()[0]
    conn.close()
    return [_agent_row_to_dict(r) for r in rows], total


def update_agent_svid(agent_id: str, svid: dict, jwt_token: str, expires_at: str):
    conn = get_conn()
    conn.execute("""
        UPDATE agents SET
            certificate_pem = ?, private_key_pem = ?, jwt_token = ?,
            cert_serial = ?, cert_not_before = ?, cert_not_after = ?,
            expires_at = ?,
            credential_rotations = credential_rotations + 1
        WHERE id = ?
    """, (
        svid["certificate_pem"], svid["private_key_pem"], jwt_token,
        svid["serial"], svid["not_before"], svid["not_after"],
        expires_at, agent_id
    ))
    conn.commit()
    conn.close()


def revoke_agent(agent_id: str):
    conn = get_conn()
    conn.execute("UPDATE agents SET status = 'revoked' WHERE id = ?", (agent_id,))
    conn.commit()
    conn.close()


def _agent_row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    d["scopes"]   = json.loads(d.get("scopes", "[]"))
    d["metadata"] = json.loads(d.get("metadata", "{}"))
    return d


# ── Audit log ─────────────────────────────────────────────────────────────────

def append_audit(agent_id: str, event: str, actor: str = "api", meta: dict = None):
    now = datetime.datetime.utcnow().isoformat() + "Z"
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_log (agent_id, event, actor, meta, ts) VALUES (?,?,?,?,?)",
        (agent_id, event, actor, json.dumps(meta or {}), now)
    )
    conn.commit()
    conn.close()


def get_audit_log(agent_id: str, limit: int = 50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE agent_id = ? ORDER BY ts DESC LIMIT ?",
        (agent_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_agent_by_spiffe(spiffe_id: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM agents WHERE spiffe_id = ?", (spiffe_id,)
    ).fetchone()
    conn.close()
    return _agent_row_to_dict(row) if row else None
