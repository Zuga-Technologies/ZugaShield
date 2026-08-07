"""Domain Outcome Contract producer — studio_id 'shield' (The Pentagon).

Lights up ZugaShield's existing city-map building (currently 'no telemetry yet')
with real security KPIs. The MM dominion-pusher polls these two endpoints every
60s and forwards to the hivemind.

Honesty law: `degraded` means the DASHBOARD itself is broken (summary build
failed). Collectors that have no data yet are NOT degraded — an empty red-team
ledger or an unbenchmarked shield is a healthy new program, reported honestly as
'no data', never as a fault.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter

import metrics

logger = logging.getLogger(__name__)

router = APIRouter(tags=["domain-outcome-contract"])

STUDIO_ID = "shield"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/domain/manifest")
async def manifest():
    return {
        "studio_id": STUDIO_ID,
        "display_name": "The Pentagon",
        "contract_version": "0.1",
        "capabilities": ["summary"],
        "visibility": "team",
        "domain": "security",
    }


@router.get("/domain/summary")
async def summary():
    try:
        return _build()
    except Exception as e:
        logger.exception("[domain] summary build failed")
        return {
            "studio_id": STUDIO_ID,
            "as_of": _now_iso(),
            "state": "degraded",
            "state_reason": f"internal error building summary: {type(e).__name__}: {e}",
            "kpis": [],
            "activity": [],
        }


# Which tiles surface as city-map KPIs (compact 4-up glance).
_KPI_TILES = ("rail_status", "open_vulns", "signatures", "red_team")


def _build() -> dict:
    m = metrics.build()
    tiles = m["tiles"]

    kpis = []
    for key in _KPI_TILES:
        t = tiles.get(key)
        if not t:
            continue
        kpis.append({
            "value": str(t["value"]),
            "label": t["label"],
            "alert": bool(t["alert"]),
            "detail": t["detail"],
        })

    activity = [
        {"at": e["at"], "line": e["line"], "alert": e["severity"] in ("critical", "high")}
        for e in m["feed"][:10]
    ]

    # Dashboard-broken is degraded; posture red/amber is real security state but
    # the dashboard is working, so state stays 'ok' and the alert rides the KPIs.
    posture = m["posture"]
    state = "ok"
    reason = f"posture: {posture['level']} — {posture['reason']}"

    return {
        "studio_id": STUDIO_ID,
        "as_of": m["as_of"],
        "state": state,
        "state_reason": reason,
        "kpis": kpis,
        "activity": activity,
    }
