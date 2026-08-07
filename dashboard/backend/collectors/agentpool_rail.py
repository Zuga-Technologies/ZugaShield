"""LIVE: AgentPool's write-time rail — the shield guarding the shared fix-pool.

The one genuinely live, persisted, queryable shield signal in the fleet today.
AgentPool runs ZugaShield (plus its own regex layers) as a write-time guard on
every posted solution and records BLOCK verdicts in SQLite, exposed at two
public GET endpoints. We pull both and diff `recent_blocks` into the event feed.

Caveat carried from the build audit: if AgentPool's Railway container has no
persistent volume mounted at /app/data, these counters reset on redeploy. The
value is still real per-deploy; long-horizon trend needs the volume confirmed.
"""

import httpx

from collectors.base import CollectResult, Event
from config import settings

COLLECTOR = "agentpool_rail"
PROVENANCE = "live"
INTERVAL = 120


async def collect() -> CollectResult:
    base = settings.agentpool_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as client:
        stats = (await client.get(f"{base}/shield/stats")).raise_for_status().json()
        trust = (await client.get(f"{base}/trust")).raise_for_status().json()

    scanned = int(stats.get("scanned_and_stored", 0))
    blocked = int(stats.get("blocked", 0))
    recent = stats.get("recent_blocks", []) or []

    payload = {
        "up": True,
        "content_shield": stats.get("content_shield", "zugashield"),
        "scanned_and_stored": scanned,
        "blocked": blocked,
        "recent_blocks": recent[:10],
        "active_entries": int(trust.get("active_entries", 0)),
        "contributors": int(trust.get("contributors", 0)),
    }

    events: list[Event] = []
    for b in recent[:10]:
        reason = str(b.get("reason", "blocked"))
        created = str(b.get("created_at", ""))
        tier = str(b.get("tier", "")) or "?"
        events.append(Event(
            kind="rail_block",
            severity="high",
            source="agentpool",
            line=f"rail BLOCKED a {tier}-tier post: {reason[:120]}",
            # created_at + reason is stable per block — dedupes across polls.
            dedupe_key=f"rail:{created}:{reason[:60]}",
        ))
    return CollectResult(payload=payload, events=events)
