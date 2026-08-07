# The Pentagon — ZugaShield's security-posture dashboard

The visual face of the security lane. Lights up ZugaShield's existing building
on the Dominion city map (`studio_id: shield`) with real security telemetry and
serves a single live dashboard page. Owner: **Justin** (security lead).

## What it shows

Every tile declares its **provenance** (LIVE auto-pulled · COMPUTED derived ·
MANUAL human-entered) and its **state** (ok · stale · no_data). An empty metric
reports "no data yet — recording since <date>", never a fake green zero.

| Signal | Provenance | Source |
|---|---|---|
| Shield rail status + blocks | LIVE | AgentPool `/shield/stats` + `/trust` |
| Signature count + severity mix + integrity drift | LIVE | `zugashield/signatures/catalog_version.json` + file counts |
| Version coherence (pkg/catalog/PyPI/tag) | LIVE | repo files + PyPI |
| Detection accuracy (TPR/FPR/p95) | COMPUTED | `benchmarks/run.py --json benchmarks/last_run.json` |
| Open issues by severity + oldest | COMPUTED | GitHub issues (public API) |
| Last red-team + bypass rate + coverage | MANUAL | `POST /api/pentagon/redteam-run` ledger |
| Five walls radar | mixed | composed from the above |

## Run locally

```bash
cd dashboard/backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m uvicorn main:app --port 8019
# open http://localhost:8019/    · API: /api/pentagon/metrics
pytest                            # 15 tests, hermetic (no network)
```

## Log a red-team campaign (makes the red-team tiles go live)

```bash
curl -X POST http://localhost:8019/api/pentagon/redteam-run \
  -H 'content-type: application/json' \
  -d '{"target":"zugashield","attempts":50,"bypasses":3,"by":"justin","note":"unicode smuggling pass"}'
```

## Deploy (Mac Mini, always-on)

```bash
bash dashboard/scripts/deploy.sh          # scp + launchd + health poll, port 8019
```
Then register on the city map: add `"shield": "http://localhost:8019"` to the
`STUDIOS` dict in `infrastructure/zuga-hivemind/scripts/mm_domain_pusher.py`, and
set the shield registry row's `dashboard_url`. The MM pusher polls `/domain/*`
every 60s and the Pentagon building shows live KPIs.

## Layout

```
dashboard/
  backend/   config.py (port 8019) · db.py · scheduler.py · metrics.py
             collectors/ (one per source) · routes/ (pentagon_api, domain) · tests/
  static/    index.html (live page, fetches /api/pentagon/metrics every 30s)
  scripts/   deploy.sh · start.sh · com.zuga.pentagon.plist
```
