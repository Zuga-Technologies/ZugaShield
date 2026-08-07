"""LIVE: version drift — package vs catalog vs PyPI vs git tag.

Four numbers that should agree and don't: the package version in _version.py,
the signature-catalog version, the latest published PyPI release, and the newest
git tag (there are currently zero tags). Surfacing the drift is the point — a
release process that publishes to PyPI on tag push is useless if nothing is
tagged.
"""

import re
import subprocess

import httpx

from collectors.base import CollectResult, Event
from config import settings

COLLECTOR = "version"
PROVENANCE = "live"
INTERVAL = 1800

_VER_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')


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


async def collect() -> CollectResult:
    pkg = _pkg_version()
    catalog = _catalog_version()
    tag = _latest_tag()
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
    if reasons:
        events.append(Event(
            kind="version_drift",
            severity="low",
            source="version",
            line="version drift: " + "; ".join(reasons),
            dedupe_key=f"vdrift:{pkg}:{catalog}:{tag}:{pypi}",
        ))
    return CollectResult(payload=payload, events=events)
