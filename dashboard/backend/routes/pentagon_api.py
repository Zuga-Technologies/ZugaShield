"""The Pentagon dashboard API.

  GET  /api/pentagon/metrics       full envelope (tiles + walls + feed + sources)
  POST /api/pentagon/redteam-run   Justin logs a red-team campaign into the ledger
"""

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException

from pydantic import BaseModel, Field

import db
import metrics
from collectors import redteam_ledger
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pentagon", tags=["pentagon"])


def _require_write_key(provided: str | None) -> None:
    """Gate writes when a key is configured. Constant-time compare. Reads stay
    open — only the coverage-mutating POST is protected."""
    expected = settings.pentagon_write_key
    if not expected:
        return  # open (dev) — production sets pentagon_write_key
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid or missing X-Pentagon-Key")


@router.get("/metrics")
async def get_metrics():
    return metrics.build()


@router.get("/redteam-coverage")
async def redteam_coverage():
    """Per-target red-team coverage + the next target due. Drives /red-team."""
    from collectors import redteam_ledger
    rows = redteam_ledger._load()
    targets, next_due = redteam_ledger._target_status(rows)
    covered = sum(1 for t in targets if t["covered"])
    return {
        "coverage_pct": round(100 * covered / len(targets)) if targets else 0,
        "covered": covered,
        "total": len(targets),
        "next_due": next_due,
        "targets": sorted(targets, key=lambda t: (t["tier"], t["covered"],
                                                  -(t["days_since"] or 0))),
    }


class RedTeamRun(BaseModel):
    target: str = Field(..., description="zugashield | zugabot.ai | studios | mcp-servers | ...")
    attempts: int = Field(..., ge=0)
    bypasses: int = Field(..., ge=0)
    by: str = Field("justin", description="who ran the campaign")
    note: str = ""


@router.post("/redteam-run")
async def log_redteam_run(run: RedTeamRun, x_pentagon_key: str | None = Header(default=None)):
    _require_write_key(x_pentagon_key)
    row = redteam_ledger.append_run(
        target=run.target, attempts=run.attempts, bypasses=run.bypasses,
        by=run.by, note=run.note,
    )
    # Also drop an immediate feed event so it shows without waiting for the poll.
    sev = "high" if run.bypasses else "info"
    db.add_event(
        "redteam_run", sev, "redteam",
        f"red-team on {run.target}: {run.attempts} attempts, {run.bypasses} bypasses ({run.by})",
        dedupe_key=f"rt:{row['at']}:{run.target}",
    )
    return {"ok": True, "logged": row}
