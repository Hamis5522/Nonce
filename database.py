"""
Nonce Database Layer
SQLite-backed persistence for local dev; Postgres-backed for production
(Render's free Postgres instance) — selected automatically via DATABASE_URL.

All public functions (create_agent, get_agent, list_agents, etc.) keep the
exact same names and signatures regardless of backend, so nothing else in
the codebase needs to change.
"""

import os
import json
import datetime

# ── Backend selection ───────────────────────────────────────────────────────
# If DATABASE_URL is set (Render provides this automatically once you attach
# a Postgres instance), use Postgres. Otherwise fall back to local SQLite —
# handy for running the server on your laptop without any extra setup.
DATABASE_URL = os.environ.get("DATABASE_URL")
IS_POSTGRES = bool(DATABASE_URL)

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras

    # Render's DATABASE_URL sometimes uses the legacy "postgres://" scheme,
    # which psycopg2 accepts, but normalize just in case something else
    # downstream expects "postgresql://".
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    import sqlite3

    DB_PATH = os.environ.get(
        "DB_PATH", os.path.join(os.path.dirname(__file__), "nonce.db")
    )


def get_conn():
    if IS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _q(sql: str) -> str:
    """Translate SQLite-style '?' placeholders to Postgres-style '%s'."""
    return sql.replace("?", "%s") if IS_POSTGRES else sql


def run(conn, sql: str, params=()):
    """
    Execute a statement and return something you can call .fetchone()/
    .fetchall() on, on either backend.
    """
    if IS_POSTGRES:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_q(sql), params)
        return cur
    else:
        return conn.execute(sql, params)


def _row_to_dict(row):
    """RealDictRow and sqlite3.Row both convert cleanly with dict()."""
    return dict(row) if row is not None else None


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()

    if IS_POSTGRES:
        schema = """
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
                id         SERIAL PRIMARY KEY,
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
        """
        cur = conn.cursor()
        cur.execute(schema)
    else:
        schema = """
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
        """
        conn.executescript(schema)

    conn.commit()
    conn.close()


# ── API Key operations ────────────────────────────────────────────────────────

def create_api_key(key_id, key_hash, key_prefix, org, name):
    now = datetime.datetime.utcnow().isoformat() + "Z"
    conn = get_conn()
    run(
        conn,
        "INSERT INTO api_keys (id, key_hash, key_prefix, org, name, created_at) VALUES (?,?,?,?,?,?)",
        (key_id, key_hash, key_prefix, org, name, now)
    )
    conn.commit()
    conn.close()


def get_api_key_by_hash(key_hash):
    conn = get_conn()
    cur = run(
        conn,
        "SELECT * FROM api_keys WHERE key_hash = ? AND revoked = 0", (key_hash,)
    )
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row)


def touch_api_key(key_id):
    now = datetime.datetime.utcnow().isoformat() + "Z"
    conn = get_conn()
    run(conn, "UPDATE api_keys SET last_used = ? WHERE id = ?", (now, key_id))
    conn.commit()
    conn.close()


def list_api_keys(org):
    conn = get_conn()
    cur = run(
        conn,
        "SELECT id, key_prefix, org, name, created_at, last_used, revoked FROM api_keys WHERE org = ?",
        (org,)
    )
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


# ── Agent operations ──────────────────────────────────────────────────────────

def create_agent(agent: dict):
    conn = get_conn()
    run(conn, """
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
        cur = run(
            conn, "SELECT * FROM agents WHERE id = ? AND org = ?", (agent_id, org)
        )
    else:
        cur = run(conn, "SELECT * FROM agents WHERE id = ?", (agent_id,))
    row = cur.fetchone()
    conn.close()
    return _agent_row_to_dict(row) if row else None


def list_agents(org: str, status: str = None, limit: int = 100, offset: int = 0):
    conn = get_conn()
    if status:
        cur = run(
            conn,
            "SELECT * FROM agents WHERE org = ? AND status = ? ORDER BY issued_at DESC LIMIT ? OFFSET ?",
            (org, status, limit, offset)
        )
        rows = cur.fetchall()
        total_cur = run(
            conn, "SELECT COUNT(*) AS c FROM agents WHERE org = ? AND status = ?", (org, status)
        )
        total = total_cur.fetchone()["c"]
    else:
        cur = run(
            conn,
            "SELECT * FROM agents WHERE org = ? ORDER BY issued_at DESC LIMIT ? OFFSET ?",
            (org, limit, offset)
        )
        rows = cur.fetchall()
        total_cur = run(conn, "SELECT COUNT(*) AS c FROM agents WHERE org = ?", (org,))
        total = total_cur.fetchone()["c"]
    conn.close()
    return [_agent_row_to_dict(r) for r in rows], total


def update_agent_svid(agent_id: str, svid: dict, jwt_token: str, expires_at: str):
    conn = get_conn()
    run(conn, """
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
    run(conn, "UPDATE agents SET status = 'revoked' WHERE id = ?", (agent_id,))
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
    run(
        conn,
        "INSERT INTO audit_log (agent_id, event, actor, meta, ts) VALUES (?,?,?,?,?)",
        (agent_id, event, actor, json.dumps(meta or {}), now)
    )
    conn.commit()
    conn.close()


def get_audit_log(agent_id: str, limit: int = 50):
    conn = get_conn()
    cur = run(
        conn,
        "SELECT * FROM audit_log WHERE agent_id = ? ORDER BY ts DESC LIMIT ?",
        (agent_id, limit)
    )
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_agent_by_spiffe(spiffe_id: str):
    conn = get_conn()
    cur = run(conn, "SELECT * FROM agents WHERE spiffe_id = ?", (spiffe_id,))
    row = cur.fetchone()
    conn.close()
    return _agent_row_to_dict(row) if row else None
