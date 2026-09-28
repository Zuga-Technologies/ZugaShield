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


def _pin_versions(monkeypatch, pkg, catalog, tag, pypi):
    monkeypatch.setattr(version, "_pkg_version", lambda: pkg)
    monkeypatch.setattr(version, "_catalog_version", lambda: catalog)
    monkeypatch.setattr(version, "_remote_latest_tag", lambda: tag)
    monkeypatch.setattr(version, "_latest_tag", lambda: tag)

    async def fake_pypi():
        return pypi
    monkeypatch.setattr(version, "_pypi_version", fake_pypi)


def _record_tickets(monkeypatch, ticket_id=501):
    filed = []

    async def fake_file(tag, pypi):
        filed.append((tag, pypi))
        return ticket_id
    monkeypatch.setattr(version, "_file_ticket", fake_file)
    return filed


def _age_state(tag, hours):
    import json
    from datetime import datetime, timedelta, timezone
    path = version._ticket_state_path()
    state = json.loads(path.read_text(encoding="utf-8"))
    state[tag]["first_seen"] = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    path.write_text(json.dumps(state), encoding="utf-8")


def test_aug7_state_tagged_but_not_on_pypi_raises_high_alarm(fresh_db, monkeypatch):
    # The exact 2026-08-07 -> 09-27 state: package, catalog and tag all 1.2.1,
    # PyPI on 1.0.2. The tile was red and NO event fired for seven weeks.
    _pin_versions(monkeypatch, "1.2.1", "1.2.1", "v1.2.1", "1.0.2")
    filed = _record_tickets(monkeypatch)

    first = asyncio.run(version.collect())
    unpub = [e for e in first.events if e.kind == "release_unpublished"]
    assert unpub and unpub[0].severity == "medium"   # inside the grace period
    assert filed == []                               # no ticket for a publish still in flight

    _age_state("v1.2.1", hours=2)
    second = asyncio.run(version.collect())
    unpub = [e for e in second.events if e.kind == "release_unpublished"]
    assert unpub and unpub[0].severity == "high"
    assert filed == [("v1.2.1", "1.0.2")]
    assert second.payload["unpublished"]["ticket"] == 501

    asyncio.run(version.collect())                   # still broken next run
    assert filed == [("v1.2.1", "1.0.2")]            # one ticket per tag, not per run


def test_pypi_catching_up_clears_the_alarm(fresh_db, monkeypatch):
    _pin_versions(monkeypatch, "1.2.2", "1.2.2", "v1.2.2", "1.2.1")
    _record_tickets(monkeypatch)
    asyncio.run(version.collect())

    _pin_versions(monkeypatch, "1.2.2", "1.2.2", "v1.2.2", "1.2.2")
    result = asyncio.run(version.collect())
    assert result.payload["coherent"] is True
    assert not any(e.kind in ("release_unpublished", "version_drift") for e in result.events)
    assert version._ticket_state_path().read_text(encoding="utf-8").strip() == "{}"


def test_pypi_unreachable_does_not_reset_the_grace_clock(fresh_db, monkeypatch):
    _pin_versions(monkeypatch, "1.2.2", "1.2.2", "v1.2.2", "1.2.1")
    _record_tickets(monkeypatch)
    asyncio.run(version.collect())
    _age_state("v1.2.2", hours=2)

    _pin_versions(monkeypatch, "1.2.2", "1.2.2", "v1.2.2", None)   # PyPI fetch failed
    asyncio.run(version.collect())

    _pin_versions(monkeypatch, "1.2.2", "1.2.2", "v1.2.2", "1.2.1")
    result = asyncio.run(version.collect())
    unpub = [e for e in result.events if e.kind == "release_unpublished"]
    assert unpub and unpub[0].severity == "high"     # still 2h old, not restarted


def test_version_bumped_but_never_tagged_is_drift(fresh_db, monkeypatch):
    _pin_versions(monkeypatch, "1.3.0", "1.3.0", "v1.2.2", "1.2.2")
    result = asyncio.run(version.collect())
    drift = [e for e in result.events if e.kind == "version_drift"]
    assert drift and "not tagged yet" in drift[0].line
    assert not any(e.kind == "release_unpublished" for e in result.events)


def test_redteam_ledger_empty_then_populated(fresh_db, monkeypatch, tmp_path):
    monkeypatch.setattr(redteam_ledger, "ledger_path", lambda: tmp_path / "rt.json")
    # Empty ledger -> honest zero runs, no fabricated activity.
    empty = asyncio.run(redteam_ledger.collect())
    assert empty.payload["runs"] == 0

    # Mixed-case target must still register as covering the normalized id.
    redteam_ledger.append_run("ZugaShield", attempts=10, bypasses=1, by="justin")
    full = asyncio.run(redteam_ledger.collect())
    assert full.payload["runs"] == 1
    assert full.payload["bypasses_total"] == 1
    assert full.payload["coverage"]["zugashield"] is True
    assert full.payload["coverage"]["trader"] is False   # untested target
    assert full.payload["coverage_pct"] > 0
    # next_due should point at an untested tier-1 target, never zugashield.
    assert full.payload["next_due"]["id"] != "zugashield"
    # A bypass on the latest run raises a feed event.
    assert any(e.kind == "redteam_bypass" for e in full.events)
