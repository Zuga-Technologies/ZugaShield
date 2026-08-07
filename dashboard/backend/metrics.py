"""Assemble the dashboard metrics envelope from stored collector snapshots.

Every tile carries `provenance` (live | computed | manual) and `state`
(ok | stale | no_data). An empty metric reports `no_data` with a
`recording_since` — it never renders as a green zero. The overall `posture`
verdict (green/amber/red) is computed only from tiles that actually have data.
"""

from datetime import datetime, timezone

import db
from collectors import REGISTRY
from config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_seconds(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except ValueError:
        return None


def _stale_threshold(cid: str) -> float:
    """A collector counts as stale only past 1.5x its own poll interval (min the
    global floor). A healthy 3600s-interval collector must NOT read 'stale' 30
    min after each run just because the global floor is 1800s."""
    mod = REGISTRY.get(cid)
    interval = getattr(mod, "INTERVAL", 900) if mod else 900
    return max(settings.stale_after_seconds, interval * 1.5)


def _collector_state(cid: str) -> tuple[str, dict | None, str | None]:
    """Return (state, snapshot, recording_since). state is a coarse freshness
    read used as a fallback; individual tiles refine it (e.g. an available:False
    benchmark snapshot is no_data even though the collector ran fine)."""
    snap = db.latest_snapshot(cid)
    last_ok = db.last_ok_run(cid)
    since = db.first_seen(cid)
    if snap is None:
        return "no_data", None, since
    age = _age_seconds(last_ok)
    if age is None or age > _stale_threshold(cid):
        return "stale", snap, since
    return "ok", snap, since


def _tile(value, label, provenance, state, detail, alert=False, recording_since=None):
    t = {
        "value": value,
        "label": label,
        "provenance": provenance,
        "state": state,
        "detail": detail,
        "alert": bool(alert),
    }
    if state == "no_data" and recording_since:
        t["recording_since"] = recording_since
    return t


def build() -> dict:
    tiles: dict[str, dict] = {}
    walls: list[dict] = []

    # --- rail (LIVE) ---
    rstate, rsnap, rsince = _collector_state("agentpool_rail")
    if rsnap:
        rail_up = rsnap.get("up")
        # State reflects real freshness (ok/stale/no_data). Only a FRESH DOWN
        # reading is an alert — a stale reading dims + notes its age instead of
        # showing a cached "UP" at full confidence (audit 1a/1c).
        tiles["rail_status"] = _tile(
            "UP" if rail_up else "DOWN",
            "shield rail",
            "live", rstate,
            "AgentPool's write-time guard — every posted fix is screened by "
            "ZugaShield before another agent can read it. UP = the gate is live. "
            "Fix: if DOWN, check the AgentPool Railway service — the fix-pool is "
            "unguarded until it's back.",
            alert=(rstate == "ok" and not rail_up),
        )
        tiles["rail_blocks"] = _tile(
            str(rsnap.get("blocked", 0)),
            "blocks (lifetime)",
            "live", rstate,
            f"Posts the rail rejected. {rsnap.get('scanned_and_stored', 0)} "
            "scanned-and-stored so far. Counts reset if AgentPool's Railway "
            "volume isn't persistent — a per-deploy figure.",
        )
    else:
        tiles["rail_status"] = _tile("—", "shield rail", "live", "no_data",
                                     "AgentPool rail not reachable yet.",
                                     recording_since=rsince)

    # --- catalog (LIVE) ---
    cstate, csnap, csince = _collector_state("catalog")
    if csnap:
        drift = csnap.get("count_drift")
        tiles["signatures"] = _tile(
            str(csnap.get("actual_total")),
            f"signatures (v{csnap.get('version')})",
            "live", cstate,
            "Live count of threat signatures across the catalog files. "
            f"Metadata declares {csnap.get('declared_total')}; drift "
            f"{drift:+d}. Fix: reconcile catalog_version.json (issue #16, Justin)."
            if drift else
            "Live count of threat signatures across the catalog files.",
            alert=bool(drift),
        )
        sev = csnap.get("severity_mix", {})
        tiles["signature_mix"] = _tile(
            f"{sev.get('critical',0)}C / {sev.get('high',0)}H",
            "sig severity mix",
            "live", cstate,
            f"Catalog severity split: {sev.get('critical',0)} critical, "
            f"{sev.get('high',0)} high, {sev.get('medium',0)} medium, "
            f"{sev.get('low',0)} low.",
        )
    else:
        tiles["signatures"] = _tile("—", "signatures", "live", "no_data",
                                    "Signature catalog not read yet.",
                                    recording_since=csince)

    # --- version drift (LIVE) ---
    vstate, vsnap, vsince = _collector_state("version")
    if vsnap:
        tiles["version"] = _tile(
            f"pkg {vsnap.get('package')} / cat {vsnap.get('catalog')}",
            "version coherence",
            "live", vstate,
            f"Package {vsnap.get('package')}, catalog {vsnap.get('catalog')}, "
            f"PyPI {vsnap.get('pypi')}, latest tag {vsnap.get('latest_tag')}. "
            "Fix: bump _version.py to the catalog version and cut a git tag "
            "(arms the PyPI release). Release decision — Justin/Buga.",
            alert=not vsnap.get("coherent"),
        )
    else:
        tiles["version"] = _tile("—", "version coherence", "live", "no_data",
                                 "Version files not read yet.",
                                 recording_since=vsince)

    # --- benchmark (COMPUTED) ---
    bstate, bsnap, bsince = _collector_state("benchmark")
    if bsnap and bsnap.get("available"):
        tiles["benchmark"] = _tile(
            f"{round(bsnap.get('tpr',0)*100)}% TPR / {round(bsnap.get('fpr',0)*100,1)}% FPR",
            "detection accuracy",
            "computed", bstate,
            f"Last benchmark {bsnap.get('ran_at')}: caught "
            f"{round(bsnap.get('tpr',0)*100)}% of {bsnap.get('attack_n')} attacks, "
            f"{round(bsnap.get('fpr',0)*100,1)}% false positives on "
            f"{bsnap.get('benign_n')} benign. p95 {bsnap.get('p95_latency_ms')}ms.",
        )
    else:
        tiles["benchmark"] = _tile(
            "no run yet", "detection accuracy", "computed", "no_data",
            "Benchmark suite exists but hasn't been run through the JSON writer "
            "yet (Phase 4). No fabricated score.",
            recording_since=bsince)

    # --- github issues (COMPUTED) ---
    istate, isnap, isince = _collector_state("github_issues")
    if isnap:
        by = isnap.get("by_severity", {})
        crit_high = by.get("critical", 0) + by.get("high", 0)
        tiles["open_vulns"] = _tile(
            str(isnap.get("open_total", 0)),
            "open issues",
            "computed", istate,
            f"Open issues on {isnap.get('repo')}. By severity: "
            f"{by.get('critical',0)}C/{by.get('high',0)}H/{by.get('medium',0)}M/"
            f"{by.get('low',0)}L, {by.get('unlabeled',0)} unlabeled. Add "
            "severity labels (Phase 4) to sharpen this.",
            alert=crit_high > 0,
        )
        age = isnap.get("oldest_open_age_days")
        tiles["oldest_open"] = _tile(
            f"{age}d" if age is not None else "none",
            "oldest open issue",
            "computed", istate,
            "Age of the oldest open issue. Not the same as 'unacknowledged' — "
            "GitHub has no ack state; an ack-label convention would sharpen it.",
            alert=bool(age and age > 30),
        )
    else:
        tiles["open_vulns"] = _tile("—", "open issues", "computed", "no_data",
                                    "GitHub issues not fetched yet.",
                                    recording_since=isince)

    # --- red team (MANUAL, empty until Justin runs one) ---
    tstate, tsnap, tsince = _collector_state("redteam_ledger")
    if tsnap and tsnap.get("runs", 0) > 0:
        nxt = (tsnap.get("next_due") or {}).get("id", "?")
        tiles["red_team"] = _tile(
            f"{tsnap.get('days_since_last')}d ago",
            "last red-team",
            "manual", tstate,
            f"{tsnap.get('runs')} campaigns, {tsnap.get('coverage_pct', 0)}% fleet "
            f"coverage. Bypass rate {tsnap.get('bypass_rate')}. Next due: {nxt}. "
            "Run `/red-team` to do today's pass.",
            alert=bool(tsnap.get("days_since_last") and tsnap["days_since_last"] > 30),
        )
    else:
        nxt = (tsnap.get("next_due") or {}).get("id", "?") if tsnap else "?"
        tiles["red_team"] = _tile(
            "none yet", "last red-team", "manual", "no_data",
            f"No campaigns logged yet. Run `/red-team` to do the first pass "
            f"(next due: {nxt}) — logs via POST /api/pentagon/redteam-run.",
            recording_since=tsince)

    # --- five walls (0-100; None = not scored yet, rendered grey not zero) ---
    walls = _build_walls(rsnap, csnap, bsnap, isnap, tsnap)

    # --- posture verdict (only from tiles that have data) ---
    # A fresh rail-DOWN or any open CRITICAL issue is hard-red; other alerts amber.
    crit_open = 0
    if isnap:
        crit_open = isnap.get("by_severity", {}).get("critical", 0)
    rail_down = bool(rsnap and rstate == "ok" and not rsnap.get("up"))
    red_reasons = []
    if rail_down:
        red_reasons.append("shield rail is DOWN")
    if crit_open:
        red_reasons.append(f"{crit_open} open CRITICAL issue(s)")
    posture = _posture(tiles, red_reasons)

    return {
        "as_of": _now_iso(),
        "posture": posture,
        "tiles": tiles,
        "walls": walls,
        "feed": db.recent_events(15),
        "sources": _sources(),
    }


def _wall(name, score, note):
    return {"name": name, "score": score,
            "state": "no_data" if score is None else "ok", "note": note}


def _build_walls(rsnap, csnap, bsnap, isnap, tsnap) -> list[dict]:
    walls = []
    # Injection Defense — from benchmark TPR if available, else catalog presence.
    if bsnap and bsnap.get("available") and bsnap.get("tpr") is not None:
        walls.append(_wall("Injection Defense", round(bsnap["tpr"] * 100),
                           "benchmark true-positive rate on attack prompts"))
    else:
        walls.append(_wall("Injection Defense", None, "needs a benchmark run"))
    # Exfiltration / DLP — same benchmark today; refine when per-layer split lands.
    if bsnap and bsnap.get("available") and bsnap.get("fpr") is not None:
        walls.append(_wall("Exfiltration / DLP", round((1 - bsnap["fpr"]) * 100),
                           "inverse false-positive rate on benign prompts"))
    else:
        walls.append(_wall("Exfiltration / DLP", None, "needs a benchmark run"))
    # Vuln Response — from open crit/high issues (fewer = higher).
    if isnap:
        by = isnap.get("by_severity", {})
        ch = by.get("critical", 0) + by.get("high", 0)
        walls.append(_wall("Vuln Response", max(0, 100 - ch * 20),
                           f"{ch} open critical/high issues"))
    else:
        walls.append(_wall("Vuln Response", None, "issues not fetched"))
    # Red-Team Coverage — fraction of expected targets with any run.
    if tsnap and tsnap.get("runs", 0) > 0:
        walls.append(_wall("Red-Team Coverage", tsnap.get("coverage_pct", 0),
                           "share of fleet targets with a logged campaign"))
    else:
        walls.append(_wall("Red-Team Coverage", None, "no campaigns yet"))
    # Dependency Hygiene — ZugaShield ships zero runtime deps by design. Verify
    # it live against pyproject.toml rather than asserting a permanent 100.
    ndeps = _runtime_dep_count()
    if ndeps is None:
        walls.append(_wall("Dependency Hygiene", None, "pyproject.toml not readable"))
    elif ndeps == 0:
        walls.append(_wall("Dependency Hygiene", 100,
                           "zero runtime dependencies (pyproject dependencies = [])"))
    else:
        walls.append(_wall("Dependency Hygiene", max(50, 100 - ndeps * 10),
                           f"{ndeps} runtime dependency(ies) — was zero by design"))
    return walls


def _runtime_dep_count() -> int | None:
    """Count entries in pyproject's [project].dependencies. None if unreadable."""
    import re
    p = settings.repo_path / "pyproject.toml"
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8")
        m = re.search(r"(?ms)^\s*dependencies\s*=\s*\[(.*?)\]", text)
        if not m:
            return None
        body = m.group(1)
        return len([x for x in re.findall(r'["\']([^"\']+)["\']', body) if x.strip()])
    except Exception:
        return None


def _posture(tiles: dict, red_reasons: list[str]) -> dict:
    """Green/amber/red from tiles that actually have data. No data ≠ red.
    red_reasons (rail-down, open critical) hard-escalate to red; any other
    alerting tile is amber."""
    if red_reasons:
        return {"level": "red", "reason": "; ".join(red_reasons)}
    alerts = [k for k, t in tiles.items()
              if t.get("alert") and t.get("state") != "no_data"]
    if alerts:
        return {"level": "amber",
                "reason": f"{len(alerts)} tile(s) need attention: {', '.join(alerts)}"}
    # No alerts, but is anything actually reporting? If everything is no_data, say so.
    live = [t for t in tiles.values() if t.get("state") != "no_data"]
    if not live:
        return {"level": "amber", "reason": "no live data yet — collectors warming up"}
    return {"level": "green", "reason": "no active alerts across reporting tiles"}


def _sources() -> list[dict]:
    out = []
    for cid, mod in REGISTRY.items():
        last = db.last_run(cid)
        out.append({
            "collector": cid,
            "provenance": getattr(mod, "PROVENANCE", "?"),
            "last_run": last["ran_at"] if last else None,
            "ok": bool(last["ok"]) if last else None,
            "error": last["error"] if last else None,
        })
    return out
