"""Collector loop — one asyncio task, per-collector intervals, crash-isolated.

Same shape as ZugaTreasury's scheduler: a single loop ticks every SECOND-ish,
each collector runs on its own interval, and a collector that raises is caught
and logged in collector_runs (never kills the loop or the other collectors).
Every run — success or failure — is recorded so staleness is measured from real
run history, not assumed.
"""

import asyncio
import logging
import time

import db
from collectors import REGISTRY
from failure_reason import normalize

logger = logging.getLogger(__name__)

TICK_SECONDS = 5


async def run_one(collector_id: str, mod) -> None:
    start = time.monotonic()
    try:
        result = await mod.collect()
        latency = int((time.monotonic() - start) * 1000)
        db.store_snapshot(collector_id, result.payload)
        for ev in result.events:
            db.add_event(ev.kind, ev.severity, ev.source, ev.line, ev.dedupe_key)
        db.record_run(collector_id, ok=True, latency_ms=latency, error=None)
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        # Contract: collectors RAISE on failure by design, so this generic
        # site cannot know the category — the raw error is preserved as
        # `unknown: <raw>` (never guessed `internal:` — a GitHub timeout is
        # not our code failing). Collectors adopt real slugs on-touch.
        db.record_run(collector_id, ok=False, latency_ms=latency,
                      error=f"{type(e).__name__}: {e}",
                      failure_reason=normalize(f"{type(e).__name__}: {e}"))
        logger.warning("collector %s failed: %s", collector_id, e)


async def run_forever() -> None:
    # Fire everything once at startup, then honor per-collector intervals.
    next_due = {cid: 0.0 for cid in REGISTRY}
    while True:
        now = time.monotonic()
        for cid, mod in REGISTRY.items():
            if now >= next_due[cid]:
                await run_one(cid, mod)
                next_due[cid] = now + getattr(mod, "INTERVAL", 900)
        await asyncio.sleep(TICK_SECONDS)
