"""COMPUTED: open security issues on the ZugaShield repo, by severity.

Reads the public GitHub REST API (ZugaShield is a public repo, so open-issue
reads need no token and stay well inside the unauthenticated rate limit at this
poll interval). Buckets by a `severity:*` or `priority:*` label; issues with no
severity label land in `unlabeled` — honest, and the nudge for Phase 4's label
convention on the bypass-report template.

Also computes the oldest-open age and emits an event when a new critical/high
issue appears.
"""

from datetime import datetime, timezone

import httpx

from collectors.base import CollectResult, Event
from config import settings

COLLECTOR = "github_issues"
PROVENANCE = "computed"
INTERVAL = 1800

_SEV_ORDER = ("critical", "high", "medium", "low")


def _severity_of(labels: list[str]) -> str | None:
    low = [x.lower() for x in labels]
    for sev in _SEV_ORDER:
        if f"severity:{sev}" in low or f"priority:{sev}" in low:
            return sev
    return None


async def collect() -> CollectResult:
    owner_repo = settings.github_repo
    url = f"https://api.github.com/repos/{owner_repo}/issues"
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "the-pentagon-dashboard"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(
            url, headers=headers,
            params={"state": "open", "per_page": 100},
        )
        r.raise_for_status()
        issues = r.json()

    # /issues returns PRs too — filter them out.
    issues = [i for i in issues if "pull_request" not in i]

    buckets = {s: 0 for s in _SEV_ORDER}
    buckets["unlabeled"] = 0
    oldest_at = None
    events: list[Event] = []
    now = datetime.now(timezone.utc)

    for i in issues:
        labels = [lbl["name"] for lbl in i.get("labels", [])]
        sev = _severity_of(labels)
        buckets[sev if sev else "unlabeled"] += 1
        created = i.get("created_at")
        if created and (oldest_at is None or created < oldest_at):
            oldest_at = created
        if sev in ("critical", "high"):
            events.append(Event(
                kind="issue_open",
                severity=sev,
                source="github",
                line=f"open {sev} issue #{i['number']}: {i['title'][:110]}",
                dedupe_key=f"issue:{i['number']}",
            ))

    oldest_age_days = None
    if oldest_at:
        dt = datetime.strptime(oldest_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        oldest_age_days = round((now - dt).total_seconds() / 86400, 1)

    payload = {
        "open_total": len(issues),
        "by_severity": buckets,
        "oldest_open_at": oldest_at,
        "oldest_open_age_days": oldest_age_days,
        "repo": owner_repo,
    }
    return CollectResult(payload=payload, events=events)
