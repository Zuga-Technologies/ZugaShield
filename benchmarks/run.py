"""
ZugaShield Detection-Accuracy Benchmark
=======================================

Runs a labelled corpus of attack and benign prompts through ZugaShield and
reports a reproducible markdown scorecard:

    - True Positive Rate  (attacks correctly flagged)
    - False Positive Rate (benign inputs incorrectly flagged)
    - Average / p95 latency per scan
    - Per-layer detection breakdown (which layer caught each attack)
    - Per-source attack detection (honest view of strengths/gaps)

A prompt is "flagged" when ZugaShield returns any verdict other than ALLOW,
matching the promptfoo assertion convention (`verdict !== 'allow'`).

Reproducibility:
    - Deterministic input order, fixed config, no network access.
    - Each prompt is scanned in its OWN session id, so the anomaly detector's
      cumulative session risk cannot leak across prompts and skew the FPR.

Usage:
    python benchmarks/run.py
    python benchmarks/run.py --limit 50
    python benchmarks/run.py --attacks path/to/attacks.jsonl --benign path/to/benign.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

from zugashield import ZugaShield
from zugashield.config import ShieldConfig

_HERE = Path(__file__).resolve().parent
_DEFAULT_ATTACKS = _HERE / "datasets" / "attacks.jsonl"
_DEFAULT_BENIGN = _HERE / "datasets" / "benign.jsonl"


def _load(path: Path, limit: int = 0) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows[:limit] if limit else rows


def _scan(shield: ZugaShield, rows: List[Dict[str, str]], tag: str) -> Tuple[List[bool], List[str], List[float]]:
    """Return (flagged_per_row, blocking_layer_per_row, latency_ms_per_row)."""
    flagged: List[bool] = []
    layers: List[str] = []
    latencies: List[float] = []
    for i, row in enumerate(rows):
        # Unique session id per prompt — judge each prompt on its own merits.
        start = time.perf_counter()
        decision = shield.check_prompt_sync(row["text"], context={"session_id": f"{tag}-{i}"})
        latencies.append((time.perf_counter() - start) * 1000.0)
        is_flagged = decision.verdict.value != "allow"
        flagged.append(is_flagged)
        layers.append(decision.layer if is_flagged else "")
    return flagged, layers, latencies


def _pct(n: int, total: int) -> str:
    return f"{(100.0 * n / total):.1f}%" if total else "n/a"


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="ZugaShield detection-accuracy benchmark")
    parser.add_argument("--attacks", type=Path, default=_DEFAULT_ATTACKS)
    parser.add_argument("--benign", type=Path, default=_DEFAULT_BENIGN)
    parser.add_argument("--limit", type=int, default=0, help="Cap samples per class (0 = all)")
    args = parser.parse_args()

    attacks = _load(args.attacks, args.limit)
    benign = _load(args.benign, args.limit)

    # Fixed config: every layer at its default, LLM judge off (no network).
    shield = ZugaShield(ShieldConfig(llm_judge_enabled=False))

    atk_flagged, atk_layers, atk_lat = _scan(shield, attacks, "atk")
    ben_flagged, _ben_layers, ben_lat = _scan(shield, benign, "ben")

    tp = sum(atk_flagged)
    fp = sum(ben_flagged)
    all_lat = atk_lat + ben_lat

    layer_counts = Counter(layer for layer in atk_layers if layer)
    source_total: Counter = Counter(r["source"] for r in attacks)
    source_hit: Counter = Counter(
        attacks[i]["source"] for i, hit in enumerate(atk_flagged) if hit
    )

    lines: List[str] = []
    lines.append("## ZugaShield Detection Benchmark\n")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Attack samples | {len(attacks)} |")
    lines.append(f"| Benign samples | {len(benign)} |")
    lines.append(f"| True Positive Rate (attacks flagged) | {_pct(tp, len(attacks))} ({tp}/{len(attacks)}) |")
    lines.append(f"| False Positive Rate (benign flagged) | {_pct(fp, len(benign))} ({fp}/{len(benign)}) |")
    lines.append(f"| Avg latency / scan | {sum(all_lat) / len(all_lat):.2f} ms |")
    lines.append(f"| p95 latency / scan | {_p95(all_lat):.2f} ms |")
    lines.append("")
    lines.append("### Per-layer detections (attacks)\n")
    lines.append("| Layer | Detections |")
    lines.append("|-------|-----------|")
    for layer, count in layer_counts.most_common():
        lines.append(f"| {layer} | {count} |")
    lines.append("")
    lines.append("### Per-source attack detection\n")
    lines.append("| Source | TPR |")
    lines.append("|--------|-----|")
    for source in sorted(source_total):
        hit, total = source_hit.get(source, 0), source_total[source]
        lines.append(f"| {source} | {_pct(hit, total)} ({hit}/{total}) |")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
