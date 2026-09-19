"""Shared pytest fixtures.

Sets fake BAZARR_URL/BAZARR_API_KEY *before* importing server.py, since the
module requires both at import time (see server._require_env). Individual
tests then swap server.client's transport to control what "Bazarr" returns,
via httpx.MockTransport — no extra mocking library needed, it ships in httpx
(already a runtime dependency).
"""

import os

os.environ.setdefault("BAZARR_URL", "http://test-bazarr:6767")
os.environ.setdefault("BAZARR_API_KEY", "test-api-key")

import httpx  # noqa: E402
import pytest  # noqa: E402

import server  # noqa: E402


@pytest.fixture
def mock_bazarr(monkeypatch):
    """Point server.client at a fake Bazarr.

    Usage:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [...]})
        mock_bazarr(handler)
    """

    def _install(handler):
        fake_client = httpx.Client(
            base_url=f"{server.BAZARR_URL}/api",
            headers={"X-API-KEY": server.BAZARR_API_KEY},
            transport=httpx.MockTransport(handler),
        )
        monkeypatch.setattr(server, "client", fake_client)
        return fake_client

    return _install


@pytest.fixture
def no_auth(monkeypatch):
    """Run with MCP_AUTH_TOKEN unset (the default, open-server mode)."""
    monkeypatch.setattr(server, "MCP_AUTH_TOKEN", None)


@pytest.fixture
def with_auth(monkeypatch):
    """Run with a known MCP_AUTH_TOKEN, and return it."""
    token = "test-shared-secret"
    monkeypatch.setattr(server, "MCP_AUTH_TOKEN", token)
    return token
