"""failure_reason contract adoption (docs/fleet/FAILURE_REASON_CONTRACT.md).

Producer under test is the REAL scheduler.run_one with fake collector
modules. Laws: success rows stay NULL, the generic catch site preserves raw
errors as `unknown: <raw>` (never guesses a category — collectors raise on
failure by design, so a GitHub timeout must not be labeled `internal:`),
migration is additive + idempotent.
"""

import asyncio
from types import SimpleNamespace

import db
import scheduler
from failure_reason import MAX_LEN, normalize


def _rows():
    return db.get_conn().execute(
        "SELECT * FROM collector_runs ORDER BY id").fetchall()


def _run_one(mod):
    asyncio.run(scheduler.run_one("testcol", mod))


# --- normalize() unit law ---------------------------------------------------

def test_normalize_none_and_blank_stay_none():
    assert normalize(None) is None
    assert normalize("   ") is None


def test_normalize_valid_category_kept_unmapped_wrapped():
    assert normalize("dependency: github 502") == "dependency: github 502"
    assert (normalize("ReadTimeout: timed out")
            == "unknown: ReadTimeout: timed out")


def test_normalize_truncates_to_max_len():
    slug = normalize("internal: " + "x" * 300)
    assert len(slug) == MAX_LEN
    assert slug.startswith("internal: ")


# --- migration law ----------------------------------------------------------

def test_migration_idempotent_and_rows_survive(fresh_db):
    db.record_run("c1", ok=False, latency_ms=5, error="boom",
                  failure_reason="dependency: boom")
    db.init_db()
    db.init_db()
    cols = [c["name"] for c in db.get_conn().execute(
        "PRAGMA table_info(collector_runs)").fetchall()]
    assert cols.count("failure_reason") == 1
    assert _rows()[0]["failure_reason"] == "dependency: boom"


# --- producer law (real scheduler.run_one) ----------------------------------

def test_ok_run_stays_null(fresh_db):
    async def collect():
        return SimpleNamespace(payload={"n": 1}, events=[])
    _run_one(SimpleNamespace(collect=collect))
    r = _rows()[-1]
    assert r["ok"] == 1
    assert r["failure_reason"] is None


def test_raising_collector_preserves_raw_as_unknown_and_survives(fresh_db):
    async def collect():
        raise TimeoutError("github api timed out after 10s")
    _run_one(SimpleNamespace(collect=collect))  # must not raise
    r = _rows()[-1]
    assert r["ok"] == 0
    assert (r["failure_reason"]
            == "unknown: TimeoutError: github api timed out after 10s")
    assert r["error"] == "TimeoutError: github api timed out after 10s"


def test_record_run_forces_null_on_ok_even_with_reason(fresh_db):
    db.record_run("c1", ok=True, latency_ms=1, error=None,
                  failure_reason="internal: should not be stored")
    assert _rows()[-1]["failure_reason"] is None


# --- surface law ------------------------------------------------------------

def test_last_run_and_last_failure_reason_expose_slug(fresh_db):
    db.record_run("c1", ok=False, latency_ms=5, error="a",
                  failure_reason="dependency: a")
    db.record_run("c1", ok=True, latency_ms=5, error=None)
    last = db.last_run("c1")
    assert last["failure_reason"] is None  # newest row is the ok one
    assert db.last_failure_reason("c1") == "dependency: a"
    assert db.last_failure_reason("never-seen") is None
