"""Collector tests that don't require network — catalog (reads the real repo
signature files), version drift logic, and the red-team ledger round-trip."""

import asyncio

from collectors import catalog, redteam_ledger, version


def test_catalog_counts_real_signatures(fresh_db):
    result = asyncio.run(catalog.collect())
    p = result.payload
    assert p["actual_total"] > 100          # real catalog has ~150 sigs
    assert p["version"]                      # version string present
    assert "critical" in p["severity_mix"]
    # If metadata drifts from the file count, an integrity event is emitted.
    if p["count_drift"] != 0:
        assert any(e.kind == "catalog_integrity" for e in result.events)


def test_version_drift_emits_event(fresh_db):
    result = asyncio.run(version.collect())
    p = result.payload
    assert "package" in p and "catalog" in p
    # Repo currently has no tags + package/catalog differ -> not coherent.
    if not p["coherent"]:
        assert any(e.kind == "version_drift" for e in result.events)


def test_redteam_ledger_empty_then_populated(fresh_db, monkeypatch, tmp_path):
    monkeypatch.setattr(redteam_ledger, "ledger_path", lambda: tmp_path / "rt.json")
    # Empty ledger -> honest zero runs, no fabricated activity.
    empty = asyncio.run(redteam_ledger.collect())
    assert empty.payload["runs"] == 0

    redteam_ledger.append_run("zugashield", attempts=10, bypasses=1, by="justin")
    full = asyncio.run(redteam_ledger.collect())
    assert full.payload["runs"] == 1
    assert full.payload["bypasses_total"] == 1
    assert full.payload["coverage"]["zugashield"] is True
    assert full.payload["coverage"]["studios"] is False
    # A bypass on the latest run raises a feed event.
    assert any(e.kind == "redteam_bypass" for e in full.events)
