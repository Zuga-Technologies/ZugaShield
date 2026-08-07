"""NO-DATA-yet → LIVE-once-Justin-runs: the red-team run ledger.

There is no dated record of red-team activity in the fleet today (CI red-team
tests are pass/fail only). This collector reads a simple append-only JSON ledger
at `data/redteam_ledger.json` that Justin (or CI) appends a row to per campaign,
via `POST /api/pentagon/redteam-run` on this service.

Empty ledger is honest, not an error: the tile reports "recording since
<first_seen>, no runs yet" until the first campaign lands. Once rows exist it
computes days-since-last-run, attempts vs bypasses, and per-target coverage.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from collectors.base import CollectResult, Event
from config import settings

COLLECTOR = "redteam_ledger"
PROVENANCE = "manual"
INTERVAL = 900

# The real fleet, tiered by attack surface (tier 1 = money/agent/auth/secrets/
# MCP — red-team these first). Coverage = which have ANY recorded run; the
# /red-team daily skill rotates through them oldest-tested-first, tier-weighted.
# Justin edits this list as the fleet changes.
EXPECTED_TARGETS: dict[str, int] = {
    # tier 1 — highest value
    "zugabot.ai": 1,        # the front door — auth, billing, ZugaTokens
    "zugabot": 1,           # the autonomous agent — sudo, self-mod, real creds
    "treasury": 1,          # company money ledger
    "trader": 1,            # live Kalshi capital + crypto wallet
    "hivemind": 1,          # team brain — auth, API keys, memory
    "agentpool-mcp": 1,     # MCP write-time rail
    "zugawatch": 1,         # MCP anomaly monitor
    "zugabot-mcp": 1,       # x402 revenue MCP
    "zugashield": 1,        # the security lib itself
    # tier 2 — user data / public surface
    "spiritus": 2,          # wellness, AI therapist, user data
    "health": 2,            # biometrics
    "ludus": 2,             # overlay + payments
    "overseer": 2,          # command dashboard
    "code": 2,              # code-review queue
    "news": 2, "docs": 2, "image": 2, "video": 2, "learn": 2, "data": 2,
    # tier 3 — lower surface (games, tooling)
    "custos": 3, "wingmate": 3, "zugacloud": 3, "zuganode": 3,
}


def ledger_path() -> Path:
    return settings.db_path.parent / "redteam_ledger.json"


def _load() -> list[dict]:
    p = ledger_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _norm(target: str) -> str:
    """Normalize a target id so 'ZugaShield' and 'zugashield ' both count as the
    same coverage key (audit 2b — exact-match silently dropped runs)."""
    return (target or "").strip().lower()


def append_run(target: str, attempts: int, bypasses: int, by: str, note: str = "") -> dict:
    """Append a red-team campaign row. Called from the API route."""
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = _load()
    row = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": _norm(target),
        "attempts": int(attempts),
        "bypasses": int(bypasses),
        "by": by,
        "note": note,
    }
    rows.append(row)
    p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return row


def _target_status(rows: list[dict]) -> tuple[list[dict], dict]:
    """Per-target coverage detail + a rotation queue. Returns (targets, next_due).
    targets: [{id, tier, last_tested, days_since, covered}] for every EXPECTED
    target. next_due: the target to red-team next — never-tested first (tier
    order), then oldest-tested. Drives the /red-team daily skill."""
    now = datetime.now(timezone.utc)
    last_at: dict[str, str] = {}
    for r in rows:
        t = _norm(r.get("target"))
        at = r.get("at", "")
        if t and (t not in last_at or at > last_at[t]):
            last_at[t] = at

    targets = []
    for tid, tier in EXPECTED_TARGETS.items():
        at = last_at.get(tid)
        days = None
        if at:
            dt = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            days = round((now - dt).total_seconds() / 86400, 1)
        targets.append({"id": tid, "tier": tier, "last_tested": at,
                        "days_since": days, "covered": at is not None})

    # next due: untested-first by tier, then oldest-tested (largest days_since).
    def _key(t):
        never = t["last_tested"] is None
        return (0 if never else 1, t["tier"] if never else 0,
                -(t["days_since"] or 0))
    nxt = sorted(targets, key=_key)[0] if targets else None
    return targets, (nxt or {})


async def collect() -> CollectResult:
    rows = _load()
    targets, next_due = _target_status(rows)
    covered_ct = sum(1 for t in targets if t["covered"])
    coverage_pct = round(100 * covered_ct / len(targets)) if targets else 0

    if not rows:
        return CollectResult(payload={
            "runs": 0,
            "targets": targets,
            "next_due": next_due,
            "coverage_pct": coverage_pct,
        })

    rows.sort(key=lambda r: r.get("at", ""))
    last = rows[-1]
    now = datetime.now(timezone.utc)
    last_dt = datetime.strptime(last["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    days_since = round((now - last_dt).total_seconds() / 86400, 1)

    attempts = sum(int(r.get("attempts", 0)) for r in rows)
    bypasses = sum(int(r.get("bypasses", 0)) for r in rows)
    covered = {_norm(r.get("target")) for r in rows}

    payload = {
        "runs": len(rows),
        "days_since_last": days_since,
        "last_target": last.get("target"),
        "attempts_total": attempts,
        "bypasses_total": bypasses,
        "bypass_rate": round(bypasses / attempts, 3) if attempts else None,
        "coverage": {t: (t in covered) for t in EXPECTED_TARGETS},
        "coverage_pct": coverage_pct,
        "targets": targets,
        "next_due": next_due,
    }
    events: list[Event] = []
    if last.get("bypasses", 0):
        events.append(Event(
            kind="redteam_bypass",
            severity="high",
            source="redteam",
            line=(f"red-team found {last['bypasses']} bypass(es) on "
                  f"{last.get('target')} ({last.get('by')})"),
            dedupe_key=f"rt:{last['at']}:{last.get('target')}",
        ))
    return CollectResult(payload=payload, events=events)
