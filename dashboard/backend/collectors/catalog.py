"""LIVE: ZugaShield signature catalog — count, severity mix, freshness.

Reads the authoritative catalog metadata file AND counts the actual signature
ids across the per-category JSON files, so it can surface the real integrity
signal: the metadata `total_signatures` (135) has drifted from the true file
count (~152). That drift is itself a dashboard-worthy finding, not something to
paper over.
"""

import json
import re

from collectors.base import CollectResult, Event
from config import settings

COLLECTOR = "catalog"
PROVENANCE = "live"
INTERVAL = 900

_ID_RE = re.compile(r'"id"\s*:')


def _sig_dir():
    return settings.repo_path / "zugashield" / "signatures"


async def collect() -> CollectResult:
    sig_dir = _sig_dir()
    meta_path = sig_dir / "catalog_version.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    declared = int(meta.get("total_signatures", 0))

    # True count: sum "id": occurrences across every category JSON (excluding the
    # metadata + integrity files themselves).
    actual = 0
    per_file: dict[str, int] = {}
    for f in sorted(sig_dir.glob("*.json")):
        if f.name in ("catalog_version.json", "integrity.json"):
            continue
        n = len(_ID_RE.findall(f.read_text(encoding="utf-8")))
        per_file[f.name] = n
        actual += n

    stats = meta.get("statistics", {})
    drift = actual - declared

    payload = {
        "version": meta.get("version"),
        "last_updated": meta.get("last_updated"),
        "declared_total": declared,
        "actual_total": actual,
        "count_drift": drift,
        "severity_mix": {
            "critical": int(stats.get("critical_severity", 0)),
            "high": int(stats.get("high_severity", 0)),
            "medium": int(stats.get("medium_severity", 0)),
            "low": int(stats.get("low_severity", 0)),
        },
        "avg_false_positive_rate": stats.get("avg_false_positive_rate"),
        "per_file": per_file,
    }

    events: list[Event] = []
    if drift != 0:
        events.append(Event(
            kind="catalog_integrity",
            severity="medium",
            source="catalog",
            line=(f"signature count drift: metadata says {declared}, files hold "
                  f"{actual} ({drift:+d}) — reconcile catalog_version.json"),
            dedupe_key=f"catalog_drift:{declared}:{actual}",
        ))
    return CollectResult(payload=payload, events=events)
