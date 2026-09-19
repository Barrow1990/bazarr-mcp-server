"""Tests for the wired-together ASGI app: /health, /ready, and the bearer-auth
middleware — via server.build_app(), the same function __main__ uses."""

import httpx
from starlette.testclient import TestClient

import server


def test_health_does_not_call_bazarr(mock_bazarr, no_auth):
    def handler(request):
        raise AssertionError("/health must not call Bazarr")

    mock_bazarr(handler)

    with TestClient(server.build_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_success(mock_bazarr, no_auth):
    mock_bazarr(lambda req: httpx.Response(200, json={"data": {"bazarr_version": "1.5.1"}}))

    with TestClient(server.build_app()) as client:
        response = client.get("/ready")

    body = response.json()
    assert response.status_code == 200
    assert body == {
        "status": "ok",
        "reachable": True,
        "authenticated": True,
        "bazarr": {"url": server.BAZARR_URL, "version": "1.5.1"},
    }


def test_ready_invalid_api_key(mock_bazarr, no_auth):
    mock_bazarr(lambda req: httpx.Response(401, json={"message": "Unauthorized"}))

    with TestClient(server.build_app()) as client:
        response = client.get("/ready")

    body = response.json()
    assert response.status_code == 503
    assert body["reachable"] is True
    assert body["authenticated"] is False
    assert "invalid Bazarr API key" in body["error"]


def test_ready_unreachable_host(mock_bazarr, no_auth):
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    mock_bazarr(handler)

    with TestClient(server.build_app()) as client:
        response = client.get("/ready")

    body = response.json()
    assert response.status_code == 503
    assert body["reachable"] is False
    assert body["authenticated"] is False


def test_ready_other_bazarr_error(mock_bazarr, no_auth):
    mock_bazarr(lambda req: httpx.Response(500, json={"message": "boom"}))

    with TestClient(server.build_app()) as client:
        response = client.get("/ready")

    body = response.json()
    assert response.status_code == 503
    assert body["reachable"] is True
    assert body["authenticated"] is True
    assert "HTTP 500" in body["error"]


def test_no_auth_token_leaves_mcp_open(mock_bazarr, no_auth):
    mock_bazarr(lambda req: httpx.Response(200, json={}))

    with TestClient(server.build_app()) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code != 401


def test_auth_token_blocks_mcp_without_header(mock_bazarr, with_auth):
    mock_bazarr(lambda req: httpx.Response(200, json={}))

    with TestClient(server.build_app()) as client:
        response = client.get("/mcp", headers={"Accept": "application/json, text/event-stream"})

    assert response.status_code == 401


def test_auth_token_blocks_mcp_with_wrong_token(mock_bazarr, with_auth):
    mock_bazarr(lambda req: httpx.Response(200, json={}))

    with TestClient(server.build_app()) as client:
        response = client.get(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": "Bearer wrong-token",
            },
        )

    assert response.status_code == 401


def test_auth_token_allows_mcp_with_correct_token(mock_bazarr, with_auth):
    mock_bazarr(lambda req: httpx.Response(200, json={}))
    token = with_auth

    with TestClient(server.build_app()) as client:
        response = client.get(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
            },
        )

    assert response.status_code != 401


def test_auth_token_does_not_block_health_or_ready(mock_bazarr, with_auth):
    mock_bazarr(lambda req: httpx.Response(200, json={"data": {"bazarr_version": "1.5.1"}}))

    with TestClient(server.build_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
