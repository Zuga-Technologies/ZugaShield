"""The Pentagon dashboard API.

  GET  /api/pentagon/metrics       full envelope (tiles + walls + feed + sources)
  POST /api/pentagon/redteam-run   Justin logs a red-team campaign into the ledger
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

import db
import metrics
from collectors import redteam_ledger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pentagon", tags=["pentagon"])


@router.get("/metrics")
async def get_metrics():
    return metrics.build()


class RedTeamRun(BaseModel):
    target: str = Field(..., description="zugashield | zugabot.ai | studios | mcp-servers | ...")
    attempts: int = Field(..., ge=0)
    bypasses: int = Field(..., ge=0)
    by: str = Field("justin", description="who ran the campaign")
    note: str = ""


@router.post("/redteam-run")
async def log_redteam_run(run: RedTeamRun):
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
