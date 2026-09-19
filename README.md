# bazarr-mcp-server

A minimal [Model Context Protocol](https://modelcontextprotocol.io) server that
connects to [Bazarr](https://www.bazarr.media) (the subtitle-manager companion
to Sonarr/Radarr), packaged for Docker.

It runs as a standing network service (streamable-http transport, not stdio),
so any MCP client on your internal network can connect to
`http://<host>:<port>/mcp` — the container isn't spawned per-client, and
container lifecycle/updates can be handed off to a tool like
[Dockhand](https://dockhand.pro).

## Tools

| Tool | Description |
|---|---|
| `list_movies` | List movies Bazarr is tracking, optionally filtered by title |
| `list_series` | List TV series Bazarr is tracking, optionally filtered by title |
| `missing_subtitles_movies` | Movies with at least one wanted subtitle language missing |
| `missing_subtitles_episodes` | Episodes with at least one wanted subtitle language missing |
| `search_movie_subtitles` | Search for and download one subtitle language for a movie |
| `search_episode_subtitles` | Search for and download one subtitle language for an episode |
| `run_wanted_search` | Trigger Bazarr's background job to search all wanted subtitles for movies or series |
| `system_status` | Bazarr version/environment info and current health issues |

`search_movie_subtitles`, `search_episode_subtitles`, and `run_wanted_search`
are the only tools that change state in Bazarr (they trigger real subtitle
searches/downloads). Everything else is read-only.

## Note on API accuracy

Bazarr was not reachable while building this server, so the tools were
written against [Bazarr's own source](https://github.com/morpheus65535/bazarr)
(`bazarr/api/`) rather than a live instance — endpoint paths, the `X-API-KEY`
auth header, and response shapes (`{"data": ..., "total": ...}` envelopes,
field names like `radarrId`/`sonarrSeriesId`/`missing_subtitles`) are read
directly out of the current `master` branch's Flask-RESTX route definitions.
Run `GET /ready` (see below) and the mocked test suite is not a substitute for
this — confirm against your real instance, and if a field is missing or an
endpoint 404s, that's real API drift to report, not a bug in guesswork.

## Health endpoints

Two plain HTTP endpoints, reachable without `MCP_AUTH_TOKEN` (so Docker's
`HEALTHCHECK`, Dockhand, or any other monitor can poll them without the
secret):

| Endpoint | Checks | Healthy | Unhealthy |
|---|---|---|---|
| `GET /health` | The process is up and serving HTTP. Does **not** call Bazarr. | `200 {"status": "ok"}` | (doesn't respond) |
| `GET /ready` | `BAZARR_URL` is reachable and `BAZARR_API_KEY` is accepted (via Bazarr's `/system/status`). | `200 {"status": "ok", "reachable": true, "authenticated": true, "bazarr": {...}}` | `503 {"status": "error", "reachable": ..., "authenticated": ..., "error": "..."}` |

Unlike the Servarr-family servers (Sonarr/Radarr/Prowlarr), there's no API-
version compatibility check here — Bazarr isn't a Servarr app and has no
equivalent unauthenticated version-discovery endpoint, and its `/api/...`
routes are unversioned.

## Authentication

Set `MCP_AUTH_TOKEN` (a random shared secret — `openssl rand -hex 32`) and
every request must carry `Authorization: Bearer <token>` or the server
returns `401`. This is checked by a small Starlette middleware in front of
the MCP app, **not** the `mcp` SDK's built-in OAuth support
(`mcp.server.auth`) — that machinery expects a full OAuth authorization
server (issuer/resource metadata, RFC 8414/8707/9068 discovery), which is
unnecessary complexity for one secret shared by trusted LAN clients.

Leave `MCP_AUTH_TOKEN` unset and the server runs with **no auth** — anything
that can reach `http://<host>:<port>/mcp` can call every tool, including the
subtitle-download and wanted-search ones. The server logs a warning on
startup when it's running this way. Either way, the trust boundary is still
the network:

- **Do not** publish this port through any reverse proxy, port-forward, or
  anything else reachable from outside your LAN/VLAN — the bearer token
  protects against anyone *on* the network, not against the open internet.
- Bind the compose `ports:` mapping to a specific internal interface (e.g.
  `192.168.1.50:8933:8933`) rather than all interfaces, if you want to be
  stricter about which hosts on your network can reach it at all.

## Configuration

Environment variables (see `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `BAZARR_URL` | yes | — | e.g. `http://192.168.1.50:6767` |
| `BAZARR_API_KEY` | yes | — | Bazarr > Settings > General > Security > API Key |
| `MCP_HOST` | no | `0.0.0.0` | Interface the server binds to inside the container |
| `MCP_PORT` | no | `8933` | Port the server listens on |
| `MCP_AUTH_TOKEN` | no | — | Shared secret required as `Authorization: Bearer <token>`. Unset = no auth (see above) |

## Image

Built and pushed to `ghcr.io/barrow1990/bazarr-mcp-server` by
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) on every push to
`main` that passes tests, tagged `:latest` and `:<commit-sha>`.
`docker-compose.yml` pulls `:latest` by default; swap in `build: .` there
instead if you'd rather build locally from the `Dockerfile`.

The image is the same three-stage build used across this family of MCP
servers: `builder` compiles dependencies into `--target=/deps`; `prep` starts
fresh from `python:3.12-alpine`, drops pip/setuptools/wheel, strips stdlib
pieces this headless server never touches, adds the non-root `app` user, and
copies in `/deps` and `server.py`; `runtime` then does a single
`COPY --from=prep / /` onto a `scratch` base — the step that actually drops
the stripped bytes from what gets pushed, rather than just hiding them in a
layered image. Expect roughly the same **~98MB** floor as the other servers
in this family (`mcp.server.request_state` unconditionally imports
`cryptography`'s AES-GCM/HKDF, so that ~15MB native extension ships
regardless). Dependencies in `requirements.txt` are pinned to exact versions.

## Running with Docker Compose

```bash
cp .env.example .env   # fill in BAZARR_URL / BAZARR_API_KEY
docker compose up -d --pull always
```

The server is then reachable at `http://<docker-host>:8933/mcp` from anything
on your internal network.

## Managing with Dockhand

Point Dockhand at `ghcr.io/barrow1990/bazarr-mcp-server` and let it track new
tags — this is the registry-pull model Dockhand's image-update tracking
(Grype/Trivy scans, tag tracking, scheduled updates) is actually built around.
The alternative, pointing Dockhand at this repo as a Git-deployed Compose
stack with `build: .`, works too, but syncing new Git commits does **not**
imply rebuilding the image — those are two separate steps for a build-from-
source stack.

**Make the GHCR package public**, or every pull will need `docker login
ghcr.io` with a PAT on each deploy host — a private package by default
requires auth even to `docker pull`, which most homelab boxes won't have
configured.

Set a restart policy of `unless-stopped` (already in `docker-compose.yml`) so
Dockhand-driven restarts and host reboots bring it back up without manual
intervention. The `HEALTHCHECK` in the `Dockerfile` (`GET /health`) drives
Docker's/Dockhand's container health status; use `GET /ready` separately if
you want to alert on Bazarr connectivity specifically rather than container
liveness.

**Environment variables in Dockhand**: `docker-compose.yml` loads
`BAZARR_URL`/`BAZARR_API_KEY`/`MCP_AUTH_TOKEN` via `env_file: [.env, .env.dockhand]`
(both optional; `.env.dockhand` loads second, so it wins for any key it also
sets). This is deliberate — a Git-deployed stack's `.env` is whatever's
checked out from the repo (i.e. `.env.example`'s placeholders, since real
`.env` is gitignored and not committed), while Dockhand writes the values you
configure in its UI to `.env.dockhand` instead.

## Connecting a client

### Claude Code

```bash
claude mcp add bazarr -s user --transport http http://<docker-host>:8933/mcp \
  --header "Authorization: Bearer <MCP_AUTH_TOKEN>"
```
(Drop the `--header` flag if you're running with `MCP_AUTH_TOKEN` unset.)

### Claude Desktop

Claude Desktop's built-in config expects a locally-spawned `command`, so for
a network server like this you'll need an HTTP-to-stdio bridge such as
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote):

```json
{
  "mcpServers": {
    "bazarr": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "http://<docker-host>:8933/mcp",
        "--header", "Authorization: Bearer <MCP_AUTH_TOKEN>"
      ]
    }
  }
}
```

## Running without Docker

```bash
pip install -r requirements.txt
BAZARR_URL=http://192.168.1.50:6767 BAZARR_API_KEY=your-api-key \
MCP_AUTH_TOKEN=your-shared-secret python server.py
```

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

- `tests/test_tools.py` — each tool's logic against a mocked Bazarr
  (`httpx.MockTransport`, no extra mocking library needed).
- `tests/test_http.py` — `/health`, `/ready`, and the bearer-auth middleware,
  via `server.build_app()` (the exact app `__main__` runs) through Starlette's
  `TestClient`.
- `tests/test_live_bazarr.py` — **opt-in** contract tests against a real
  Bazarr instance, to catch drift if a Bazarr upgrade renames/removes a field
  these tools depend on (`radarrId`, `sonarrSeriesId`, `missing_subtitles`,
  `bazarr_version`, ...). Skipped by default (no Bazarr in CI); run with:
  ```bash
  RUN_LIVE_BAZARR_TESTS=1 BAZARR_URL=https://bazarr.example.com \
  BAZARR_API_KEY=<real key> python -m pytest tests/test_live_bazarr.py -v
  ```

CI (`.github/workflows/ci.yml`) runs the mocked suite on every push/PR; the
GHCR build only runs after it passes.

## License

MIT
