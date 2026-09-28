"""LIVE: version drift — package vs catalog vs PyPI vs git tag.

Four numbers that should agree: the package version in _version.py, the
signature-catalog version, the latest published PyPI release, and the newest
git tag.

The one that matters most is "a v* tag exists on GitHub but PyPI never got it":
a release was cut and failed. v1.2.0/v1.2.1 sat in exactly that state for seven
weeks (2026-08-07 -> 09-27) with this tile red and NO event, because the drift
reasons below never compared the tag to PyPI. Now that state raises a high event
and files one Hivemind ticket per tag once it has persisted past a grace period.

Tags come from GitHub (git ls-remote), not the local checkout: the Mac Mini's
checkout only fetches when the Pentagon is redeployed, so its tags go stale.
"""

import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from collectors.base import CollectResult, Event
from collectors.perimeter import _hivemind_auth, _load_json, _save_json
from config import settings

COLLECTOR = "version"
PROVENANCE = "live"
INTERVAL = 1800

# A tag push normally reaches PyPI in ~1-2 minutes. Past this, it failed.
UNPUBLISHED_GRACE = timedelta(hours=1)

_VER_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


def _vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _pkg_version() -> str | None:
    vf = settings.repo_path / "zugashield" / "_version.py"
    if not vf.exists():
        return None
    m = _VER_RE.search(vf.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def _catalog_version() -> str | None:
    import json
    cf = settings.repo_path / "zugashield" / "signatures" / "catalog_version.json"
    if not cf.exists():
        return None
    return json.loads(cf.read_text(encoding="utf-8")).get("version")


def _latest_tag() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(settings.repo_path), "tag", "--sort=-creatordate"],
            capture_output=True, text=True, timeout=10,
        )
        tags = [t for t in out.stdout.splitlines() if t.strip()]
        return tags[0] if tags else None
    except Exception:
        return None


async def _pypi_version() -> str | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get("https://pypi.org/pypi/zugashield/json")
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json().get("info", {}).get("version")
    except Exception:
        return None


def _remote_latest_tag() -> str | None:
    """Highest v* tag on GitHub right now, or None if unreachable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(settings.repo_path), "ls-remote", "--tags", "--refs", "origin", "v*"],
            capture_output=True, text=True, timeout=20,
        )
        if out.returncode != 0:
            return None
        tags = [ln.split("refs/tags/", 1)[1] for ln in out.stdout.splitlines() if "refs/tags/" in ln]
        return max(tags, key=_vkey) if tags else None
    except Exception:
        return None


def _ticket_state_path() -> Path:
    return settings.db_path.parent / "version_tickets.json"


async def _file_ticket(tag: str, pypi: str) -> int | None:
    """One Hivemind ticket for a tag PyPI never got. None when not configured."""
    auth = _hivemind_auth()
    if auth is None:
        return None
    headers, extra = auth
    title = f"[release] ZugaShield {tag} is tagged on GitHub but PyPI still serves {pypi}"
    body = (
        f"The Pentagon sees tag {tag} on GitHub, but https://pypi.org/project/zugashield/ "
        f"still serves {pypi}, more than {int(UNPUBLISHED_GRACE.total_seconds() // 60)} "
        "minutes after the tag first appeared. The release workflow's PyPI publish failed "
        "or never ran.\n\n"
        "1. Open the Release run for this tag: "
        "https://github.com/Zuga-Technologies/ZugaShield/actions/workflows/release.yml\n"
        "2. If Publish to PyPI says `invalid-publisher`, the PyPI Trusted Publisher is missing "
        "or changed. A PyPI OWNER of zugashield fixes it at "
        "https://pypi.org/manage/project/zugashield/settings/publishing/ "
        "(owner Zuga-Technologies, repo ZugaShield, workflow release.yml, environment pypi).\n"
        "3. Re-run the failed job: `gh run rerun <run id> -R Zuga-Technologies/ZugaShield "
        "--failed`. GitHub refuses re-runs after 30 days; past that, cut the next patch "
        "version instead.\n\n"
        "Filed by the Pentagon version collector, once per tag.")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{settings.hivemind_url.rstrip('/')}/report", headers=headers,
            json={"kind": "bug", "title": title, "body": body,
                  "reporter": "pentagon-version", "product": "zugashield",
                  "priority": "high", "source": "agent",
                  "source_ref": f"pentagon:version:{tag}", **extra})
        r.raise_for_status()
        return r.json().get("id")


async def _unpublished_tag_event(tag: str, pypi: str) -> tuple[Event, dict]:
    """Medium while inside the grace period, then high plus one ticket per tag."""
    path = _ticket_state_path()
    state = {k: v for k, v in _load_json(path, {}).items() if k == tag}
    now = datetime.now(timezone.utc)
    entry = state.setdefault(tag, {"first_seen": now.isoformat()})
    age = now - datetime.fromisoformat(entry["first_seen"])
    info = {"tag": tag, "pypi": pypi, "first_seen": entry["first_seen"],
            "ticket": entry.get("ticket")}
    if age < UNPUBLISHED_GRACE:
        severity = "medium"
        line = f"release {tag} tagged, waiting for PyPI (serves {pypi})"
    else:
        severity = "high"
        line = f"release {tag} is tagged but PyPI still serves {pypi}: the PyPI publish failed"
        if not entry.get("ticket"):
            try:
                tid = await _file_ticket(tag, pypi)
                if tid:
                    entry["ticket"] = tid
                    info["ticket"] = tid
                else:
                    info["ticketing"] = "off (no hivemind credential)"
            except Exception as e:  # retried next run
                info["ticket_error"] = f"{type(e).__name__}: {e}"
    _save_json(path, state)
    return Event(kind="release_unpublished", severity=severity, source="version",
                 line=line, dedupe_key=f"unpublished:{tag}:{pypi}:{severity}"), info


async def collect() -> CollectResult:
    pkg = _pkg_version()
    catalog = _catalog_version()
    tag = _remote_latest_tag() or _latest_tag()
    pypi = await _pypi_version()

    versions = {v for v in (pkg, catalog, pypi) if v}
    coherent = len(versions) <= 1 and tag is not None

    payload = {
        "package": pkg,
        "catalog": catalog,
        "pypi": pypi or "unpublished",
        "latest_tag": tag or "none",
        "coherent": coherent,
    }

    events: list[Event] = []
    reasons = []
    if pkg and catalog and pkg != catalog:
        reasons.append(f"package {pkg} != catalog {catalog}")
    if tag is None:
        reasons.append("no git tags — PyPI release workflow never triggers")
    if pypi is None:
        reasons.append("not published to PyPI")
    elif pkg and _vkey(pkg) > _vkey(pypi) and not (tag and _vkey(tag) >= _vkey(pkg)):
        reasons.append(f"package {pkg} is ahead of PyPI {pypi} and not tagged yet")
    if reasons:
        events.append(Event(
            kind="version_drift",
            severity="low",
            source="version",
            line="version drift: " + "; ".join(reasons),
            dedupe_key=f"vdrift:{pkg}:{catalog}:{tag}:{pypi}",
        ))

    if tag and pypi and _vkey(tag) > _vkey(pypi):
        event, payload["unpublished"] = await _unpublished_tag_event(tag, pypi)
        events.append(event)
    elif tag and pypi:
        # PyPI has caught up, so a later failure is a new finding. Not cleared when
        # PyPI or GitHub was unreachable: that would restart the grace clock.
        _save_json(_ticket_state_path(), {})
    return CollectResult(payload=payload, events=events)
