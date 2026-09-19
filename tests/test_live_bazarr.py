"""Live contract tests against a *real* Bazarr instance.

These do not run by default — there's no Bazarr in CI, and we don't want to
accidentally fire real requests using the fake BAZARR_URL/BAZARR_API_KEY that
conftest.py sets for the rest of the suite. To run them:

    RUN_LIVE_BAZARR_TESTS=1 BAZARR_URL=https://bazarr.example.com \\
    BAZARR_API_KEY=<real key> pytest tests/test_live_bazarr.py -v

Point is to catch drift: if a Bazarr upgrade renames/removes a field our
tools depend on (radarrId, sonarrSeriesId, missing_subtitles, ...), these
fail even though the mocked unit tests in test_tools.py would still happily
pass (they only assert against fixtures we wrote ourselves).
"""

import os

import httpx
import pytest

import server

RUN_LIVE = os.environ.get("RUN_LIVE_BAZARR_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="opt-in only: set RUN_LIVE_BAZARR_TESTS=1 with a real BAZARR_URL/BAZARR_API_KEY",
)


@pytest.fixture(scope="module")
def live_client():
    return httpx.Client(
        base_url=f"{server.BAZARR_URL}/api",
        headers={"X-API-KEY": server.BAZARR_API_KEY},
        timeout=15,
    )


def test_system_status_shape(live_client):
    """The fields system_status()/`/ready` depend on actually exist."""
    response = live_client.get("/system/status")
    response.raise_for_status()
    data = response.json()["data"]

    assert "bazarr_version" in data


def test_movie_shape_matches_what_list_movies_assumes(live_client):
    """Every field list_movies() reads exists on a real Bazarr response."""
    response = live_client.get("/movies", params={"length": -1})
    response.raise_for_status()
    movies = response.json()["data"]

    if not movies:
        pytest.skip("no movies tracked — nothing to validate the shape of")

    sample = movies[0]
    for required_field in ("radarrId", "title"):
        assert required_field in sample, f"Bazarr's /movies no longer returns '{required_field}'"


def test_series_shape_matches_what_list_series_assumes(live_client):
    """Every field list_series() reads exists on a real Bazarr response."""
    response = live_client.get("/series", params={"length": -1})
    response.raise_for_status()
    series = response.json()["data"]

    if not series:
        pytest.skip("no series tracked — nothing to validate the shape of")

    sample = series[0]
    for required_field in ("sonarrSeriesId", "title"):
        assert required_field in sample, f"Bazarr's /series no longer returns '{required_field}'"


def test_our_tools_run_cleanly_against_real_bazarr(monkeypatch, live_client):
    """Run the actual tool functions (not just raw requests) against real Bazarr."""
    monkeypatch.setattr(server, "client", live_client)

    status = server.system_status()
    assert "bazarr_version" in status["status"]

    movies = server.list_movies()
    assert isinstance(movies, list)

    series = server.list_series()
    assert isinstance(series, list)
