"""SQLite (WAL) storage for The Pentagon.

Three tables, all append-only or last-write-per-collector — never fabricated:
  - `collector_runs`  one row per collector execution (staleness comes from
                      here, never from a made-up "fresh" flag).
  - `snapshots`       the latest JSON payload per collector; the metrics API
                      reads the most recent row per collector.
  - `events`          append-only security-event ledger feeding the threat
                      feed (rail blocks, issues opened, version drift, red-team
                      runs). Real events only.

`collector_first_seen` records when each collector first ran, so a metric with
no data yet can honestly say "recording since <date>, no events" instead of
faking a zero-that-looks-green.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone

from config import settings

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS collector_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    collector   TEXT NOT NULL,
    ran_at      TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    latency_ms  INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_collector ON collector_runs(collector, ran_at);

CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    collector    TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snap_collector ON snapshots(collector, captured_at);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    kind        TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'info' CHECK (severity IN
                  ('critical','high','medium','low','info')),
    source      TEXT NOT NULL,
    line        TEXT NOT NULL,
    dedupe_key  TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_events_at ON events(at);

CREATE TABLE IF NOT EXISTS collector_first_seen (
    collector   TEXT PRIMARY KEY,
    first_at    TEXT NOT NULL
);
"""


def get_conn() -> sqlite3.Connection:
    """Per-thread connection (uvicorn worker threads + the collector loop)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(settings.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        _local.conn = conn
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    # failure_reason contract (docs/fleet/FAILURE_REASON_CONTRACT.md):
    # additive nullable column; duplicate-column on re-run is the expected
    # steady state, anything else re-raises.
    try:
        conn.execute("ALTER TABLE collector_runs ADD COLUMN failure_reason TEXT")
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            raise
    conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_run(collector: str, ok: bool, latency_ms: int | None, error: str | None,
               failure_reason: str | None = None) -> None:
    conn = get_conn()
    now = _now_iso()
    conn.execute(
        "INSERT INTO collector_runs (collector, ran_at, ok, latency_ms, error, "
        "failure_reason) VALUES (?, ?, ?, ?, ?, ?)",
        (collector, now, 1 if ok else 0, latency_ms, error,
         None if ok else failure_reason),
    )
    conn.execute(
        "INSERT OR IGNORE INTO collector_first_seen (collector, first_at) VALUES (?, ?)",
        (collector, now),
    )
    conn.commit()


def store_snapshot(collector: str, payload: dict) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO snapshots (collector, captured_at, payload) VALUES (?, ?, ?)",
        (collector, _now_iso(), json.dumps(payload)),
    )
    conn.commit()


def latest_snapshot(collector: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT payload, captured_at FROM snapshots WHERE collector = ? "
        "ORDER BY captured_at DESC LIMIT 1",
        (collector,),
    ).fetchone()
    if not row:
        return None
    data = json.loads(row["payload"])
    data["_captured_at"] = row["captured_at"]
    return data


def last_ok_run(collector: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT ran_at FROM collector_runs WHERE collector = ? AND ok = 1 "
        "ORDER BY ran_at DESC LIMIT 1",
        (collector,),
    ).fetchone()
    return row["ran_at"] if row else None


def last_run(collector: str) -> sqlite3.Row | None:
    conn = get_conn()
    return conn.execute(
        "SELECT ran_at, ok, error, failure_reason FROM collector_runs "
        "WHERE collector = ? ORDER BY ran_at DESC LIMIT 1",
        (collector,),
    ).fetchone()


def last_failure_reason(collector: str) -> str | None:
    """Newest slug-classified reason for this collector (contract surface)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT failure_reason FROM collector_runs WHERE collector = ? "
        "AND failure_reason IS NOT NULL ORDER BY id DESC LIMIT 1",
        (collector,),
    ).fetchone()
    return row["failure_reason"] if row else None


def first_seen(collector: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT first_at FROM collector_first_seen WHERE collector = ?",
        (collector,),
    ).fetchone()
    return row["first_at"] if row else None


def add_event(kind: str, severity: str, source: str, line: str,
              dedupe_key: str | None = None) -> bool:
    """Append a real security event. Returns False if deduped (already seen)."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO events (at, kind, severity, source, line, dedupe_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_now_iso(), kind, severity, source, line, dedupe_key),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # dedupe_key collision — already recorded


def recent_events(limit: int = 15) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT at, kind, severity, source, line FROM events "
        "ORDER BY at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def reset_for_tests() -> None:
    """Close this thread's cached connection so tests can repoint the db path."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
