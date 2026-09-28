"""LIVE: the public perimeter — every route that answers to nobody.

Every hostname the Cloudflare tunnel publishes is a door. This collector reads
that list from the tunnel's own config, builds one pool of GET routes from every
service it can see (each tunnel service's local /openapi.json, plus the Zugabot
backend's route dump, because openapi is off there), then requests every route
in the pool through every public hostname with no credentials.

Why the whole pool through every door, not each host's own routes: on
2026-09-27 mobile.zugabot.ai turned out to be a reverse proxy to the backend.
Its own route table was a static site; through it, 53 backend routes answered
200 to anyone. Only probing the pool through every door catches a proxy.

Verdicts, per (host, route):
  open      2xx that is not the host's catch-all page. Open and listed in
            perimeter_allowlist.json (with a why) is by design; open and not
            listed is a finding: red tile, feed event, and one hivemind ticket
            for Justin per batch of newly seen routes.
  suspect   5xx. The request reached the route with no auth in front of it and
            only a crash kept it shut (09-27: /api/schedule/now was 500 only
            because its tick was off; tick on = calendar public).
  fallback  2xx identical to what the host returns for a made-up path (a static
            site's index.html). Not a door.
  auth / absent / redirect / other / unreachable — closed or not there.

Read-only: GETs with no credentials, once a day.
"""

import asyncio
import fnmatch
import hashlib
import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

from collectors.base import CollectResult, Event
from config import settings

logger = logging.getLogger(__name__)

COLLECTOR = "perimeter"
PROVENANCE = "live"
INTERVAL = 86400

ALLOWLIST_PATH = Path(__file__).resolve().parent.parent / "perimeter_allowlist.json"

# Made-up paths. What a host returns for these is its catch-all answer.
CANARIES = ("/pentagon-perimeter-canary", "/api/pentagon-perimeter-canary")

CONCURRENCY = 6
TIMEOUT = 10.0
BODY_CAP = 65536       # bytes read per response (an SSE stream never ends)
BODY_DEADLINE = 5.0    # seconds spent reading one body
DUMP_TIMEOUT = 180

# Tests swap in an httpx.MockTransport; None = the real network.
_transport = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the doors: the tunnel's ingress list ---------------------------------------

def _ingress_entries(text: str) -> list[dict]:
    """The `- hostname: / service:` entries of a cloudflared config.yml. A line
    starting with '-' opens a new entry. No YAML dependency: the file is flat."""
    entries: list[dict] = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^\s*(-\s+)?(hostname|service|path):\s*(\S+)", line)
        if not m:
            continue
        if m.group(1):
            cur = {}
            entries.append(cur)
        if cur is not None:
            cur[m.group(2)] = m.group(3)
    return entries


def _local_port(service: str) -> int | None:
    m = re.match(r"^(https?)://(?:localhost|127\.0\.0\.1)(?::(\d+))?", service or "")
    if not m:
        return None
    return int(m.group(2)) if m.group(2) else (443 if m.group(1) == "https" else 80)


def parse_tunnel_hosts(text: str) -> dict[str, int]:
    """hostname -> local port, for every ingress entry that is a real web door.
    The catch-all (`service: http_status:404`) has no hostname and is skipped."""
    hosts = {}
    for e in _ingress_entries(text):
        host, port = e.get("hostname"), _local_port(e.get("service", ""))
        if host and "*" not in host and port:
            hosts[host] = port
    return hosts


def unswept_hosts(text: str) -> list[dict]:
    """Published hostnames this sweep cannot probe (wildcards, non-HTTP
    services). Listed in the payload so a blind spot is visible, not silent."""
    return [{"hostname": e["hostname"], "service": e.get("service", "")}
            for e in _ingress_entries(text)
            if e.get("hostname") and ("*" in e["hostname"]
                                      or not _local_port(e.get("service", "")))]


# --- the routes: one pool from every service we can see ----------------------------

def openapi_paths(spec: dict) -> list[str]:
    """Param-free GET paths from an OpenAPI document."""
    return sorted(p for p, ops in (spec.get("paths") or {}).items()
                  if "get" in ops and "{" not in p)


def dump_paths(text: str) -> list[str]:
    """Param-free GET paths from route_dump.py output ('GET,HEAD /path' lines)."""
    out = set()
    for line in text.splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2 and "GET" in parts[0].split(",") and "{" not in parts[1]:
            out.add(parts[1].strip())
    return sorted(out)


async def dump_backend_routes() -> list[str]:
    """The Zugabot backend's route table, from its own dumper (openapi is off
    there on purpose). Runs the backend's venv against its checkout."""
    if not settings.zugabot_repo_path:
        return []
    repo = Path(settings.zugabot_repo_path).expanduser()
    py = (Path(settings.zugabot_python).expanduser() if settings.zugabot_python
          else repo / "backend" / ".venv" / "bin" / "python")
    script = repo / "scripts" / "prune" / "route_dump.py"
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "routes.txt"
        proc = await asyncio.create_subprocess_exec(
            str(py), str(script), str(repo), str(out),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), DUMP_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"route dump timed out after {DUMP_TIMEOUT}s")
        if proc.returncode != 0:
            # The last lines of a traceback name the failure.
            tail = " | ".join(err.decode(errors="replace").strip().splitlines()[-3:])
            raise RuntimeError(f"route dump exited {proc.returncode}: {tail}")
        return dump_paths(out.read_text(encoding="utf-8"))


def _cache_path() -> Path:
    return settings.db_path.parent / "perimeter_routes.json"


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


async def route_pool(client: httpx.AsyncClient, hosts: dict[str, int]) -> tuple[list[str], list[dict]]:
    """Union of every source's GET routes, plus a per-source report. A source
    that fails falls back to its last good list, marked as cached, so one broken
    dumper never quietly shrinks the sweep."""
    cache = _load_json(_cache_path(), {})

    async def openapi(port: int) -> list[str]:
        r = await client.get(f"http://127.0.0.1:{port}/openapi.json")
        r.raise_for_status()
        return openapi_paths(r.json())

    jobs = [(f"localhost:{port}/openapi.json", lambda port=port: openapi(port))
            for port in sorted(set(hosts.values()))]
    if settings.zugabot_repo_path:
        jobs.append(("zugabot backend route dump", dump_backend_routes))

    pool: set[str] = set()
    sources = []
    for name, fetch in jobs:
        src = {"source": name, "routes": 0}
        try:
            paths = await fetch()
            cache[name] = {"at": _now_iso(), "paths": paths}
        except Exception as e:  # recorded in the payload, never silent
            src["error"] = f"{type(e).__name__}: {e}"
            paths = (cache.get(name) or {}).get("paths", [])
            if paths:
                src["cached_from"] = cache[name]["at"]
        src["routes"] = len(paths)
        pool.update(paths)
        sources.append(src)
    _save_json(_cache_path(), cache)
    return sorted(pool), sources


# --- the sweep ------------------------------------------------------------------------

async def _read_capped(resp: httpx.Response) -> bytes:
    buf = bytearray()

    async def pull():
        async for chunk in resp.aiter_bytes():
            buf.extend(chunk)
            if len(buf) >= BODY_CAP:
                return

    try:
        await asyncio.wait_for(pull(), BODY_DEADLINE)
    except (asyncio.TimeoutError, httpx.HTTPError):
        pass  # the status line is the verdict; a stalled body doesn't change it
    return bytes(buf[:BODY_CAP])


async def _probe(client, sem, host: str, path: str) -> dict:
    row = {"host": host, "path": path, "status": None, "bytes": 0, "type": "", "sha": ""}
    async with sem:
        try:
            async with client.stream("GET", f"https://{host}{path}") as resp:
                row["status"] = resp.status_code
                row["type"] = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                body = await _read_capped(resp)
        except httpx.HTTPError as e:
            row["error"] = f"{type(e).__name__}: {e}"
            return row
    row["bytes"] = len(body)
    row["sha"] = hashlib.sha256(body).hexdigest()
    return row


def _client(transport=None) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=transport or _transport, timeout=TIMEOUT,
                             follow_redirects=False,
                             headers={"User-Agent": "the-pentagon-perimeter"})


async def sweep(hosts: list[str], paths: list[str], transport=None) -> list[dict]:
    """GET every path (plus the canaries) on every host, with no credentials."""
    sem = asyncio.Semaphore(CONCURRENCY)
    targets = [(h, p) for h in hosts for p in (*CANARIES, *sorted(set(paths)))]
    async with _client(transport) as client:
        return list(await asyncio.gather(*(_probe(client, sem, h, p) for h, p in targets)))


# --- the verdict -----------------------------------------------------------------------

def load_allowlist(path: Path = ALLOWLIST_PATH) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("routes", [])


def allowed_by(host: str, path: str, allowlist: list[dict]) -> dict | None:
    for entry in allowlist:
        if (fnmatch.fnmatchcase(host, entry.get("host", ""))
                and fnmatch.fnmatchcase(path, entry.get("path", ""))):
            return entry
    return None


def _classify(p: dict, canaries: list[dict], origin_down: bool) -> str:
    s = p["status"]
    if s is None:
        return "unreachable"
    if 200 <= s < 300:
        for c in canaries:
            if c["sha"] == p["sha"] or (
                    c["type"] == p["type"] == "text/html" and c["bytes"] == p["bytes"]):
                return "fallback"
        return "open"
    if s in (401, 403):
        return "auth"
    if s in (404, 405, 410):
        return "absent"
    if 300 <= s < 400:
        return "redirect"
    if s >= 500:
        # Every path 5xx, made-up ones too, is a dead origin, not a suspect route.
        return "unreachable" if origin_down else "suspect"
    return "other"


def summarize(probes: list[dict], allowlist: list[dict]) -> dict:
    canary_rows: dict[str, list[dict]] = {}
    for p in probes:
        if p["path"] in CANARIES:
            canary_rows.setdefault(p["host"], []).append(p)

    hosts: dict[str, dict] = {}
    unknown_open, unknown_suspect, allowed_open = [], [], []
    for p in probes:
        if p["path"] in CANARIES:
            continue
        host = p["host"]
        cans = canary_rows.get(host, [])
        origin_down = bool(cans) and all((c["status"] or 0) >= 500 for c in cans)
        h = hosts.setdefault(host, {k: 0 for k in (
            "probes", "open", "suspect", "fallback", "auth", "absent",
            "redirect", "other", "unreachable")})
        h["origin_down"] = origin_down
        h["probes"] += 1
        verdict = _classify(p, [c for c in cans if c["status"] and 200 <= c["status"] < 300],
                            origin_down)
        h[verdict] += 1
        if verdict not in ("open", "suspect"):
            continue
        entry = {"host": host, "path": p["path"], "status": p["status"], "bytes": p["bytes"]}
        allow = allowed_by(host, p["path"], allowlist)
        if allow:
            allowed_open.append({**entry, "why": allow.get("why", "")})
        elif verdict == "open":
            unknown_open.append(entry)
        else:
            unknown_suspect.append(entry)
    return {"hosts": hosts, "unknown_open": unknown_open,
            "unknown_suspect": unknown_suspect, "allowed_open": allowed_open}


# --- tickets for Justin -------------------------------------------------------------

def _ticket_state_path() -> Path:
    return settings.db_path.parent / "perimeter_tickets.json"


def _hivemind_auth() -> tuple[dict, dict] | None:
    """(headers, extra body) for POST /report, or None when no credential is set."""
    if settings.hivemind_api_key:
        return {"X-API-Key": settings.hivemind_api_key}, {}
    if settings.hivemind_admin_token:
        return {"X-Admin-Token": settings.hivemind_admin_token}, {"filed_by": "pentagon"}
    return None


def _ticket_text(new: list[dict]) -> tuple[str, str]:
    hosts = ", ".join(sorted({r["host"] for r in new}))
    title = f"[perimeter] {len(new)} unknown open route(s) on {hosts} (for Justin)"
    lines = [f"- GET https://{r['host']}{r['path']} -> {r['status']} ({r['bytes']} bytes)"
             for r in new]
    body = (
        "The Pentagon's perimeter sweep requested these routes with no credentials "
        "and got a 2xx. None is listed in ZugaShield "
        "dashboard/backend/perimeter_allowlist.json.\n\n" + "\n".join(lines) +
        "\n\nFix, one of:\n"
        "1. Put auth on the route, or take the hostname off the tunnel "
        "(~/.cloudflared/config.yml on the Mac Mini).\n"
        "2. If it is public on purpose, add it to perimeter_allowlist.json with a "
        "why and who decided.\n\n"
        "For: Justin (security lane). Filed by the Pentagon perimeter collector; "
        "it will not file these routes again while they stay open.")
    return title, body


async def ticket_new_routes(client: httpx.AsyncClient, unknown_open: list[dict]) -> dict:
    """File ONE ticket for routes not ticketed before. A route that closes drops
    out of the state file, so if it opens again it is a new finding."""
    path = _ticket_state_path()
    current = {f"{r['host']} {r['path']}" for r in unknown_open}
    state = {k: v for k, v in _load_json(path, {}).items() if k in current}
    new = [r for r in unknown_open if f"{r['host']} {r['path']}" not in state]
    auth = _hivemind_auth()
    out = {"configured": auth is not None, "filed": [], "not_yet_ticketed": len(new)}
    if new and auth:
        headers, extra = auth
        title, body = _ticket_text(new)
        try:
            r = await client.post(
                f"{settings.hivemind_url.rstrip('/')}/report", headers=headers,
                json={"kind": "bug", "title": title, "body": body,
                      "reporter": "pentagon-perimeter", "product": "zugashield",
                      "priority": "high", "source": "agent",
                      "source_ref": "pentagon:perimeter", **extra})
            r.raise_for_status()
            tid = r.json().get("id")
            for row in new:
                state[f"{row['host']} {row['path']}"] = {"ticket": tid, "at": _now_iso()}
            out["filed"] = [tid]
            out["not_yet_ticketed"] = 0
        except Exception as e:  # retried next run; the tile shows the error
            out["error"] = f"{type(e).__name__}: {e}"
    out["tickets"] = sorted({v["ticket"] for v in state.values() if v.get("ticket")})
    _save_json(path, state)
    return out


def _events(summary: dict) -> list[Event]:
    events = []
    for key, kind, severity, what in (
            ("unknown_open", "perimeter_open", "high", "answered 2xx with no credentials"),
            ("unknown_suspect", "perimeter_suspect", "medium",
             "answered 5xx with no credentials (reached, no auth in front)")):
        by_host: dict[str, list[str]] = {}
        for r in summary[key]:
            by_host.setdefault(r["host"], []).append(r["path"])
        for host, paths in sorted(by_host.items()):
            digest = hashlib.sha1("\n".join(sorted(paths)).encode()).hexdigest()
            events.append(Event(
                kind=kind, severity=severity, source="perimeter",
                line=f"{len(paths)} unknown route(s) on {host} {what} (full list: perimeter tile)",
                dedupe_key=f"{kind}:{host}:{digest}"))
    return events


async def collect() -> CollectResult:
    text = Path(settings.cloudflared_config_path).expanduser().read_text(encoding="utf-8")
    hosts = parse_tunnel_hosts(text)
    if not hosts:
        raise RuntimeError("tunnel config lists no sweepable hostname")

    async with _client() as client:
        pool, sources = await route_pool(client, hosts)
        probes = await sweep(sorted(hosts), pool)
        if not any(p["status"] is not None for p in probes):
            raise RuntimeError(f"sweep reached no public host ({len(probes)} requests failed)")
        summary = summarize(probes, load_allowlist())
        ticketing = await ticket_new_routes(client, summary["unknown_open"])

    for host, port in hosts.items():
        summary["hosts"].setdefault(host, {})["port"] = port
    payload = {
        "swept_at": _now_iso(),
        "paths_probed": len(pool),
        "requests": len(probes),
        "route_sources": sources,
        "unswept": unswept_hosts(text),
        **summary,
        "ticketing": ticketing,
    }
    return CollectResult(payload=payload, events=_events(summary))
