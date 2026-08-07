"""Shared collector plumbing.

Each collector module exposes:
  COLLECTOR   str — stable id (also the snapshots/collector_runs key)
  PROVENANCE  "live" | "computed" | "manual"
  INTERVAL    int — seconds between runs
  async collect() -> dict — the snapshot payload (raw metric data)

A collector NEVER invents freshness: if it can't reach its source it raises,
the scheduler logs the failure in collector_runs, and the metrics API reports
that tile as `stale` (last good value + age) rather than a fake current number.
"""

from dataclasses import dataclass, field


@dataclass
class Event:
    """A real security event to append to the threat-feed ledger."""

    kind: str
    severity: str  # critical|high|medium|low|info
    source: str
    line: str
    dedupe_key: str | None = None


@dataclass
class CollectResult:
    payload: dict
    events: list[Event] = field(default_factory=list)
