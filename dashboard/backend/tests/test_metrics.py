import asyncio

import db
import metrics
from routes import domain


def test_empty_build_is_honest_not_fake_green(fresh_db):
    m = metrics.build()
    # No snapshots yet -> every tile that can be no_data says so.
    assert m["tiles"]["benchmark"]["state"] == "no_data"
    assert m["tiles"]["red_team"]["state"] == "no_data"
    # Posture must NOT be green when nothing is reporting.
    assert m["posture"]["level"] in ("amber", "red")
    assert m["posture"]["level"] != "green"


def test_no_data_tiles_never_alert_as_red_posture(fresh_db):
    # A red-team tile with no data is not an alert -> must not force red.
    m = metrics.build()
    assert m["tiles"]["red_team"]["alert"] is False


def test_rail_and_signatures_render_when_present(fresh_db):
    db.store_snapshot("agentpool_rail", {"up": True, "blocked": 3,
                                         "scanned_and_stored": 40})
    db.record_run("agentpool_rail", ok=True, latency_ms=10, error=None)
    db.store_snapshot("catalog", {"version": "1.2.0", "actual_total": 152,
                                  "declared_total": 135, "count_drift": 17,
                                  "severity_mix": {"critical": 55, "high": 48,
                                                   "medium": 25, "low": 7}})
    db.record_run("catalog", ok=True, latency_ms=8, error=None)
    m = metrics.build()
    assert m["tiles"]["rail_status"]["value"] == "UP"
    assert m["tiles"]["rail_blocks"]["value"] == "3"
    assert m["tiles"]["signatures"]["value"] == "152"
    # count drift flips the signatures tile to alert.
    assert m["tiles"]["signatures"]["alert"] is True


def test_rail_down_forces_red_posture(fresh_db):
    db.store_snapshot("agentpool_rail", {"up": False, "blocked": 0,
                                         "scanned_and_stored": 0})
    db.record_run("agentpool_rail", ok=True, latency_ms=10, error=None)
    m = metrics.build()
    assert m["posture"]["level"] == "red"


def test_walls_null_scores_are_no_data_not_zero(fresh_db):
    m = metrics.build()
    by_name = {w["name"]: w for w in m["walls"]}
    assert by_name["Injection Defense"]["score"] is None
    assert by_name["Injection Defense"]["state"] == "no_data"
    # Dependency hygiene is a real 100 (zero deps by design).
    assert by_name["Dependency Hygiene"]["score"] == 100


def test_domain_summary_ok_when_empty(fresh_db):
    out = asyncio.run(domain.summary())
    # Dashboard works even with no data -> state ok (posture rides the reason).
    assert out["state"] == "ok"
    assert out["studio_id"] == "shield"


def test_domain_manifest_is_shield(fresh_db):
    out = asyncio.run(domain.manifest())
    assert out["studio_id"] == "shield"
    assert out["display_name"] == "The Pentagon"
    assert out["domain"] == "security"
