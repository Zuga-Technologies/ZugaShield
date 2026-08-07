import db


def test_snapshot_roundtrip(fresh_db):
    db.store_snapshot("catalog", {"actual_total": 152})
    snap = db.latest_snapshot("catalog")
    assert snap["actual_total"] == 152
    assert "_captured_at" in snap


def test_latest_snapshot_none_when_empty(fresh_db):
    assert db.latest_snapshot("nope") is None


def test_run_recording_and_first_seen(fresh_db):
    db.record_run("catalog", ok=True, latency_ms=12, error=None)
    assert db.last_ok_run("catalog") is not None
    assert db.first_seen("catalog") is not None
    # first_seen is stable across further runs
    first = db.first_seen("catalog")
    db.record_run("catalog", ok=False, latency_ms=5, error="boom")
    assert db.first_seen("catalog") == first
    last = db.last_run("catalog")
    assert last["ok"] == 0 and "boom" in last["error"]


def test_event_dedupe(fresh_db):
    assert db.add_event("x", "low", "s", "line one", dedupe_key="k1") is True
    assert db.add_event("x", "low", "s", "line one again", dedupe_key="k1") is False
    events = db.recent_events()
    assert len(events) == 1


def test_recent_events_order(fresh_db):
    db.add_event("a", "low", "s", "first")
    db.add_event("b", "high", "s", "second")
    events = db.recent_events()
    assert events[0]["line"] == "second"  # newest first
