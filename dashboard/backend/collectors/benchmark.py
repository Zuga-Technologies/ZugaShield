"""COMPUTED: detection-accuracy benchmark (TPR / FPR / latency).

ZugaShield's benchmark suite (`benchmarks/run.py`) measures true-positive rate
on 180 attack prompts, false-positive rate on 110 benign prompts, and p95
latency — but today it only prints markdown to stdout, leaving no datable
record. Phase 4 adds a `--json <path>` writer that drops `benchmarks/last_run.json`;
this collector reads that file.

Until that file exists the metric is honestly `no_data` (a missing benchmark
score is not an error — it just hasn't been run through the new writer yet), so
we return `available: False` rather than raising.
"""

import json

from collectors.base import CollectResult
from config import settings

COLLECTOR = "benchmark"
PROVENANCE = "computed"
INTERVAL = 3600


def _score_path():
    return settings.repo_path / "benchmarks" / "last_run.json"


async def collect() -> CollectResult:
    p = _score_path()
    if not p.exists():
        return CollectResult(payload={"available": False})
    data = json.loads(p.read_text(encoding="utf-8"))
    payload = {
        "available": True,
        "ran_at": data.get("ran_at"),
        "tpr": data.get("tpr"),          # attacks correctly flagged
        "fpr": data.get("fpr"),          # benign wrongly flagged
        "p95_latency_ms": data.get("p95_latency_ms"),
        "attack_n": data.get("attack_n"),
        "benign_n": data.get("benign_n"),
    }
    return CollectResult(payload=payload)
