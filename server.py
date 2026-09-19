"""
Bazarr MCP Server

Exposes a small set of Bazarr (subtitle manager for Sonarr/Radarr) operations
as MCP tools, so an MCP-compatible AI assistant (e.g. Claude Code / Claude
Desktop) can browse tracked movies/series, check what's missing subtitles,
and trigger subtitle downloads via Bazarr's REST API.

Configuration is via environment variables:
  BAZARR_URL        e.g. http://192.168.1.50:6767 (required)
  BAZARR_API_KEY    Bazarr > Settings > General > Security > API Key (required)
  MCP_HOST          interface to bind to (default 0.0.0.0)
  MCP_PORT          port to listen on (default 8933)
  MCP_AUTH_TOKEN    shared secret required as `Authorization: Bearer <token>`
                    on every request (optional — if unset, the server is open
                    to anyone who can reach it; see README for why that's a
                    real trade-off, not just a default to ignore)

Bazarr is not a Servarr app (unlike Sonarr/Radarr/Prowlarr) — it has no
unauthenticated `/api` version-discovery endpoint, so there is no
BAZARR_API_VERSION and no equivalent version check in /ready. Its API is
unversioned at `/api/...`, authenticated via an `X-API-KEY` header checked by
Bazarr's own `authenticate` decorator (bazarr/api/utils.py), which also
accepts the key as an `apikey` query/form field — this server only ever uses
the header form.

Transport: streamable-http. This runs as a standing network service (bind
0.0.0.0 inside the container; publish the port only on your internal
network/VLAN — never forward it externally) rather than being spawned
per-client over stdio, so any MCP client on the LAN can connect to
http://<host>:<port>/mcp.

Auth here is a single shared bearer token checked by plain middleware, not
the SDK's built-in OAuth support (mcp.server.auth) — that machinery expects
a full OAuth authorization server (issuer/resource metadata, RFC 8414/8707/
9068 discovery), which is unwarranted complexity for a single internal
secret shared by trusted LAN clients.
"""

import hmac
import os
import sys

import httpx
import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"error: required environment variable {name} is not set", file=sys.stderr)
        sys.exit(1)
    return value


BAZARR_URL = _require_env("BAZARR_URL").rstrip("/")
BAZARR_API_KEY = _require_env("BAZARR_API_KEY")
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MCP_PORT", "8933"))
MCP_AUTH_TOKEN = os.environ.get("MCP_AUTH_TOKEN")

client = httpx.Client(
    base_url=f"{BAZARR_URL}/api",
    headers={"X-API-KEY": BAZARR_API_KEY},
    timeout=30,
)

mcp = MCPServer("bazarr")


@mcp.tool()
def list_movies(title: str | None = None) -> list[dict]:
    """List movies Bazarr is tracking for subtitles, optionally filtered by a title substring."""
    response = client.get("/movies", params={"length": -1})
    response.raise_for_status()
    movies = response.json()["data"]

    if title:
        needle = title.lower()
        movies = [m for m in movies if needle in m["title"].lower()]

    return [
        {
            "radarrId": m["radarrId"],
            "title": m["title"],
            "year": m.get("year"),
            "monitored": m.get("monitored"),
            "missing_subtitles": m.get("missing_subtitles"),
            "subtitles": m.get("subtitles"),
            "audio_language": m.get("audio_language"),
        }
        for m in movies
    ]


@mcp.tool()
def list_series(title: str | None = None) -> list[dict]:
    """List TV series Bazarr is tracking for subtitles, optionally filtered by a title substring."""
    response = client.get("/series", params={"length": -1})
    response.raise_for_status()
    series = response.json()["data"]

    if title:
        needle = title.lower()
        series = [s for s in series if needle in s["title"].lower()]

    return [
        {
            "sonarrSeriesId": s["sonarrSeriesId"],
            "title": s["title"],
            "year": s.get("year"),
            "monitored": s.get("monitored"),
            "episodeFileCount": s.get("episodeFileCount"),
            "episodeMissingCount": s.get("episodeMissingCount"),
            "audio_language": s.get("audio_language"),
        }
        for s in series
    ]


@mcp.tool()
def missing_subtitles_movies() -> list[dict]:
    """List movies that have at least one wanted subtitle language missing."""
    response = client.get("/movies/wanted", params={"length": -1})
    response.raise_for_status()
    return response.json()["data"]


@mcp.tool()
def missing_subtitles_episodes() -> list[dict]:
    """List TV episodes that have at least one wanted subtitle language missing."""
    response = client.get("/episodes/wanted", params={"length": -1})
    response.raise_for_status()
    return response.json()["data"]


@mcp.tool()
def search_movie_subtitles(radarr_id: int, language: str, forced: bool = False, hi: bool = False) -> str:
    """Trigger Bazarr to search for and download a subtitle in one language for a movie already in the library.

    `language` is a two-letter code (e.g. "en", "fr") as shown in Bazarr's own language list.
    """
    response = client.patch(
        "/movies/subtitles",
        data={
            "radarrid": radarr_id,
            "language": language,
            "forced": str(forced),
            "hi": str(hi),
        },
    )
    response.raise_for_status()
    return f"Subtitle download triggered for movie {radarr_id} ({language})"


@mcp.tool()
def search_episode_subtitles(
    series_id: int, episode_id: int, language: str, forced: bool = False, hi: bool = False
) -> str:
    """Trigger Bazarr to search for and download a subtitle in one language for an episode already in the library.

    `language` is a two-letter code (e.g. "en", "fr") as shown in Bazarr's own language list.
    """
    response = client.patch(
        "/episodes/subtitles",
        data={
            "seriesid": series_id,
            "episodeid": episode_id,
            "language": language,
            "forced": str(forced),
            "hi": str(hi),
        },
    )
    response.raise_for_status()
    return f"Subtitle download triggered for episode {episode_id} ({language})"


@mcp.tool()
def run_wanted_search(media_type: str) -> str:
    """Trigger Bazarr's background job that searches for all wanted/missing subtitles.

    `media_type` must be "movies" or "series". This searches everything in
    that library's wanted list at once, rather than one item at a time.
    """
    task_ids = {
        "movies": "wanted_search_missing_subtitles_movies",
        "series": "wanted_search_missing_subtitles_series",
    }
    if media_type not in task_ids:
        raise ValueError('media_type must be "movies" or "series"')

    response = client.post("/system/tasks", data={"taskid": task_ids[media_type]})
    response.raise_for_status()
    return f"Wanted-subtitles search triggered for {media_type}"


@mcp.tool()
def system_status() -> dict:
    """Get Bazarr version/environment info and current health issues."""
    status, health = (
        client.get("/system/status").json()["data"],
        client.get("/system/health").json()["data"],
    )
    return {"status": status, "health": health}


# Paths that must stay reachable without MCP_AUTH_TOKEN, so Docker's own
# HEALTHCHECK, Dockhand's health probe, etc. don't need the secret.
UNAUTHENTICATED_PATHS = {"/health", "/ready"}


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    """Liveness check: the process is up and serving HTTP. Does not call Bazarr."""
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/ready", methods=["GET"])
async def ready(request: Request) -> Response:
    """Readiness check: BAZARR_URL is reachable and BAZARR_API_KEY is valid.

    Bazarr has no version-discovery endpoint like the Servarr apps
    (Sonarr/Radarr/Prowlarr), so unlike those servers' /ready, there is no
    API-version compatibility check here — just reachability and auth.
    """
    try:
        response = client.get("/system/status", timeout=5)
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        status_code = error.response.status_code
        reason = "invalid Bazarr API key" if status_code == 401 else f"Bazarr returned HTTP {status_code}"
        return JSONResponse(
            {"status": "error", "reachable": True, "authenticated": status_code != 401, "error": reason},
            status_code=503,
        )
    except httpx.RequestError as error:
        return JSONResponse(
            {
                "status": "error",
                "reachable": False,
                "authenticated": False,
                "error": f"cannot reach Bazarr at {BAZARR_URL}: {error}",
            },
            status_code=503,
        )

    return JSONResponse(
        {
            "status": "ok",
            "reachable": True,
            "authenticated": True,
            "bazarr": {"url": BAZARR_URL, "version": response.json()["data"].get("bazarr_version")},
        }
    )


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require `Authorization: Bearer <MCP_AUTH_TOKEN>` on every request except
    the health/readiness endpoints, which are meant to be publicly pollable."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path in UNAUTHENTICATED_PATHS:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, MCP_AUTH_TOKEN):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def build_app():
    """Build the ASGI app (routes + auth middleware). Split out from __main__ so
    tests can exercise the real, fully-wired app without going through uvicorn."""
    app = mcp.streamable_http_app(host=MCP_HOST)

    if MCP_AUTH_TOKEN:
        app.add_middleware(BearerTokenMiddleware)
        print("Auth enabled: Authorization: Bearer <token> required", file=sys.stderr)
    else:
        print("WARNING: MCP_AUTH_TOKEN not set — server is open to anyone who can reach it", file=sys.stderr)

    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host=MCP_HOST, port=MCP_PORT)
