# ZugaShield Detection Benchmark

A reproducible scorecard for ZugaShield's prompt-detection accuracy.

```bash
pip install -e .
python benchmarks/run.py
```

## What it measures

| Metric | Meaning |
|--------|---------|
| **True Positive Rate** | Fraction of attack prompts flagged (verdict != `allow`) |
| **False Positive Rate** | Fraction of benign prompts wrongly flagged |
| **Avg / p95 latency** | Per-scan wall-clock (first ML call pays a one-time model-load cost) |
| **Per-layer detections** | Which layer caught each attack (`prompt_armor`, `ml_detector`, …) |
| **Per-source TPR** | Detection broken out by corpus source — honest view of strengths/gaps |

A prompt is "flagged" when `check_prompt_sync` returns any verdict other than
`ALLOW`, matching the promptfoo assertion convention (`verdict !== 'allow'`).

## Datasets (`datasets/`)

- **`attacks.jsonl`** (180) — extracted from the committed promptfoo corpora:
  `injection_attacks`, `encoding_evasion`, `unicode_smuggling` (the families
  ZugaShield targets) plus a capped slice of `redteam_generated` (broad
  red-team suite incl. harmful-content / bias prompts).
- **`benign.jsonl`** (110) — curated legitimate prompts (coding, data, writing,
  business, support, math, casual). No committed benign corpus existed in the
  repo (the coverage tests pull `deepset` from HuggingFace at runtime, which is
  not offline-reproducible), so this set is authored here.

Each line is `{"text": ..., "source": ...}`.

## Reproducibility

- Deterministic input order, fixed config, no network (`llm_judge` off).
- Each prompt is scanned under its **own** session id, so the anomaly
  detector's cumulative session risk cannot leak across prompts and inflate
  the FPR. Accuracy numbers are stable run-to-run; only latency varies.

## Known findings this surfaces

- Overall TPR is dragged down by `redteam_generated`, which contains
  harmful-content / bias prompts that ZugaShield (an injection/exfiltration
  shield, **not** a content-safety filter) is not designed to block. Curated
  injection / unicode sources score ~100%; see the per-source table.
- The `ml_detector` produces a small benign false-positive rate (a few clearly
  innocuous prompts flagged). These are intentionally kept in `benign.jsonl` —
  measuring that FPR is the point. Reducing it is model-training work, tracked
  separately.
