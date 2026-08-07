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

# Targets we expect a mature security program to cover — coverage = which of
# these has ANY recorded red-team run.
EXPECTED_TARGETS = ("zugashield", "zugabot.ai", "studios", "mcp-servers")


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


def append_run(target: str, attempts: int, bypasses: int, by: str, note: str = "") -> dict:
    """Append a red-team campaign row. Called from the API route."""
    p = ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = _load()
    row = {
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": target,
        "attempts": int(attempts),
        "bypasses": int(bypasses),
        "by": by,
        "note": note,
    }
    rows.append(row)
    p.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return row


async def collect() -> CollectResult:
    rows = _load()
    if not rows:
        return CollectResult(payload={"runs": 0})

    rows.sort(key=lambda r: r.get("at", ""))
    last = rows[-1]
    now = datetime.now(timezone.utc)
    last_dt = datetime.strptime(last["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    days_since = round((now - last_dt).total_seconds() / 86400, 1)

    attempts = sum(int(r.get("attempts", 0)) for r in rows)
    bypasses = sum(int(r.get("bypasses", 0)) for r in rows)
    covered = {r.get("target") for r in rows}

    payload = {
        "runs": len(rows),
        "days_since_last": days_since,
        "last_target": last.get("target"),
        "attempts_total": attempts,
        "bypasses_total": bypasses,
        "bypass_rate": round(bypasses / attempts, 3) if attempts else None,
        "coverage": {t: (t in covered) for t in EXPECTED_TARGETS},
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
