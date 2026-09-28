"""Perimeter collector tests. No network: every public host and every local
openapi document is served by an httpx.MockTransport. The 09-27 mobile side-door
sweep is replayed as the regression fixture."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

import db
import metrics
from collectors import perimeter
from config import settings

FIXTURE = Path(__file__).parent / "fixtures" / "perimeter_mobile_sweep_20260927.json"

# ~/.cloudflared/config.yml on the Mac as it stood on 09-27, before the mobile
# hostname was removed.
TUNNEL_CONFIG = """\
tunnel: 00000000-0000-0000-0000-000000000000
credentials-file: /Users/zugabot/.cloudflared/x.json

ingress:
  - hostname: treasury-api.zugabot.ai
    service: http://localhost:8017
  - hostname: api.zugabot.ai
    service: http://localhost:8001
  - hostname: mobile.zugabot.ai
    service: http://localhost:3001
  - hostname: pentagon.zugabot.ai
    service: http://localhost:8019
  - service: http_status:404
"""

SPA = b"<!doctype html><html><body><div id=app></div></body></html>"


def _mobile_rows():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["routes"]


def _mobile_handler(request: httpx.Request) -> httpx.Response:
    """mobile.zugabot.ai on 09-27: static PWA for everything, /api/* proxied
    to the backend (which 404s unknown paths)."""
    path = request.url.path
    if path.startswith("/api/"):
        for r in _mobile_rows():
            if r["path"] == path:
                return httpx.Response(r["status"], content=b"x" * r["bytes"],
                                      headers={"content-type": "application/json"})
        return httpx.Response(404, json={"detail": "Not Found"})
    return httpx.Response(200, content=SPA, headers={"content-type": "text/html"})


# --- parsing -----------------------------------------------------------------

def test_tunnel_hosts_map_hostname_to_local_port_and_skip_catchall():
    assert perimeter.parse_tunnel_hosts(TUNNEL_CONFIG) == {
        "treasury-api.zugabot.ai": 8017,
        "api.zugabot.ai": 8001,
        "mobile.zugabot.ai": 3001,
        "pentagon.zugabot.ai": 8019,
    }


def test_openapi_paths_keeps_only_param_free_gets():
    spec = {"paths": {
        "/a": {"get": {}},
        "/b": {"post": {}},
        "/c/{id}": {"get": {}},
        "/d": {"get": {}, "post": {}},
    }}
    assert perimeter.openapi_paths(spec) == ["/a", "/d"]


def test_route_dump_output_keeps_only_param_free_gets():
    text = "GET,HEAD /x\nWS /ws/y\nPOST /z\nGET /a/{id}\nDELETE,GET /q"
    assert perimeter.dump_paths(text) == ["/q", "/x"]


# --- classification -----------------------------------------------------------

def test_mobile_side_door_replay_flags_every_open_route():
    """Regression: the 09-27 side door. 53 backend routes answered 200 to
    nobody through mobile.zugabot.ai; the collector must flag all 53."""
    paths = [r["path"] for r in _mobile_rows()]
    probes = asyncio.run(perimeter.sweep(["mobile.zugabot.ai"], paths,
                                         transport=httpx.MockTransport(_mobile_handler)))
    summary = perimeter.summarize(probes, perimeter.load_allowlist())
    assert len(summary["unknown_open"]) == 53
    assert {"host": "mobile.zugabot.ai", "path": "/api/budget/status",
            "status": 200, "bytes": 16722} in summary["unknown_open"]
    # the three 500s (e.g. /api/schedule/now, open but broken) are suspects
    assert {p["path"] for p in summary["unknown_suspect"]} == {
        "/api/admin/access-codes", "/api/autonomous/management/loops/status",
        "/api/schedule/now"}


def test_spa_fallback_page_is_not_an_open_route():
    """A static site answers 200 + index.html for any path. That is not a door."""
    spa = httpx.MockTransport(lambda req: httpx.Response(
        200, content=SPA, headers={"content-type": "text/html"}))
    probes = asyncio.run(perimeter.sweep(["mobile.zugabot.ai"], ["/health", "/api/x"],
                                         transport=spa))
    summary = perimeter.summarize(probes, [])
    assert summary["unknown_open"] == []
    assert summary["hosts"]["mobile.zugabot.ai"]["fallback"] == 2


def test_allowlisted_open_route_is_not_unknown():
    ok = httpx.MockTransport(lambda req: httpx.Response(200, json={"ok": True})
                             if "canary" not in req.url.path
                             else httpx.Response(404))
    probes = asyncio.run(perimeter.sweep(["pentagon.zugabot.ai"],
                                         ["/api/pentagon/metrics"], transport=ok))
    summary = perimeter.summarize(probes, perimeter.load_allowlist())
    assert summary["unknown_open"] == []
    assert summary["allowed_open"][0]["path"] == "/api/pentagon/metrics"
    assert summary["allowed_open"][0]["why"]


def test_allowlist_entry_for_one_host_does_not_cover_another():
    allow = [{"host": "pentagon.zugabot.ai", "path": "/health/live", "why": "probe"}]
    assert perimeter.allowed_by("pentagon.zugabot.ai", "/health/live", allow)
    assert perimeter.allowed_by("mobile.zugabot.ai", "/health/live", allow) is None


# --- the collector end to end ---------------------------------------------------

@pytest.fixture()
def wired(fresh_db, monkeypatch, tmp_path):
    """collect() wired to the 09-27 world: tunnel config on disk, local openapi
    documents, the backend route dump, the public hosts, and hivemind — all
    answered by one MockTransport. Returns the list of hivemind POST bodies."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(TUNNEL_CONFIG, encoding="utf-8")
    monkeypatch.setattr(settings, "cloudflared_config_path", str(cfg))
    monkeypatch.setattr(settings, "hivemind_api_key", "test-key")
    backend_paths = [r["path"] for r in _mobile_rows()]

    async def fake_dump():
        return backend_paths
    monkeypatch.setattr(perimeter, "dump_backend_routes", fake_dump)

    tickets: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in ("127.0.0.1", "localhost"):
            if request.url.port == 8019:
                return httpx.Response(200, json={"paths": {
                    "/api/pentagon/metrics": {"get": {}}, "/": {"get": {}}}})
            return httpx.Response(404)
        if host == "hivemind.test":
            assert request.headers.get("x-api-key") == "test-key"
            tickets.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "id": 900 + len(tickets)})
        if host == "mobile.zugabot.ai":
            return _mobile_handler(request)
        if host == "pentagon.zugabot.ai" and request.url.path in (
                "/api/pentagon/metrics", "/"):
            return httpx.Response(200, json={})
        return httpx.Response(403)

    monkeypatch.setattr(settings, "hivemind_url", "https://hivemind.test")
    monkeypatch.setattr(perimeter, "_transport", httpx.MockTransport(handler))
    return tickets


def test_collect_files_one_ticket_for_new_open_routes_then_dedupes(wired):
    first = asyncio.run(perimeter.collect())
    assert len(first.payload["unknown_open"]) == 53
    assert first.payload["ticketing"]["filed"] == [901]
    assert len(wired) == 1
    assert "justin" in wired[0]["body"].lower()
    assert "/api/budget/status" in wired[0]["body"]
    assert any(e.kind == "perimeter_open" and e.severity == "high"
               for e in first.events)

    second = asyncio.run(perimeter.collect())
    assert len(second.payload["unknown_open"]) == 53
    assert second.payload["ticketing"]["filed"] == []
    assert len(wired) == 1


def test_collect_without_hivemind_credentials_says_ticketing_is_off(wired, monkeypatch):
    monkeypatch.setattr(settings, "hivemind_api_key", "")
    monkeypatch.setattr(settings, "hivemind_admin_token", "")
    result = asyncio.run(perimeter.collect())
    assert result.payload["ticketing"]["configured"] is False
    assert wired == []


def test_collect_raises_when_no_public_host_answers(fresh_db, monkeypatch, tmp_path):
    """Never a fake all-clear: if the sweep reached nothing, the tile goes stale."""
    cfg = tmp_path / "config.yml"
    cfg.write_text(TUNNEL_CONFIG, encoding="utf-8")
    monkeypatch.setattr(settings, "cloudflared_config_path", str(cfg))

    async def fake_dump():
        return ["/api/budget/status"]
    monkeypatch.setattr(perimeter, "dump_backend_routes", fake_dump)

    def down(request):
        raise httpx.ConnectError("no route to host")
    monkeypatch.setattr(perimeter, "_transport", httpx.MockTransport(down))
    with pytest.raises(RuntimeError):
        asyncio.run(perimeter.collect())


def test_unknown_open_route_turns_posture_red(wired):
    result = asyncio.run(perimeter.collect())
    db.store_snapshot("perimeter", result.payload)
    db.record_run("perimeter", ok=True, latency_ms=1, error=None)
    out = metrics.build()
    assert out["tiles"]["perimeter"]["alert"] is True
    assert out["tiles"]["perimeter"]["value"].startswith("53")
    assert out["posture"]["level"] == "red"
    assert "perimeter" in out["posture"]["reason"]
