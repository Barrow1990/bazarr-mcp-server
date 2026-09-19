"""Unit tests for each MCP tool's logic, against a mocked Bazarr.

`@mcp.tool()` returns the original function unchanged, so these call the
tools directly as plain Python functions — no MCP protocol/session machinery
involved here (that's covered separately in test_http.py).
"""

import json

import httpx
import pytest

import server

SAMPLE_MOVIES = [
    {
        "radarrId": 1,
        "title": "Chernobyl",
        "year": "2019",
        "monitored": True,
        "missing_subtitles": [],
        "subtitles": [{"name": "English", "code2": "en"}],
        "audio_language": [{"name": "English"}],
    },
    {
        "radarrId": 2,
        "title": "The Wire",
        "year": "2002",
        "monitored": True,
        "missing_subtitles": [{"name": "French", "code2": "fr"}],
        "subtitles": [],
        "audio_language": [{"name": "English"}],
    },
]

SAMPLE_SERIES = [
    {
        "sonarrSeriesId": 10,
        "title": "The Bear",
        "year": "2022",
        "monitored": True,
        "episodeFileCount": 20,
        "episodeMissingCount": 2,
        "audio_language": [{"name": "English"}],
    }
]


def test_list_movies_returns_shaped_records(mock_bazarr):
    mock_bazarr(lambda req: httpx.Response(200, json={"data": SAMPLE_MOVIES, "total": 2}))

    result = server.list_movies()

    assert len(result) == 2
    assert result[0]["radarrId"] == 1
    assert result[0]["title"] == "Chernobyl"


def test_list_movies_filters_by_title_case_insensitive(mock_bazarr):
    mock_bazarr(lambda req: httpx.Response(200, json={"data": SAMPLE_MOVIES, "total": 2}))

    result = server.list_movies(title="wire")

    assert len(result) == 1
    assert result[0]["title"] == "The Wire"


def test_list_movies_propagates_http_errors(mock_bazarr):
    mock_bazarr(lambda req: httpx.Response(500, json={"message": "boom"}))

    with pytest.raises(httpx.HTTPStatusError):
        server.list_movies()


def test_list_series_returns_shaped_records(mock_bazarr):
    mock_bazarr(lambda req: httpx.Response(200, json={"data": SAMPLE_SERIES, "total": 1}))

    result = server.list_series()

    assert len(result) == 1
    assert result[0]["sonarrSeriesId"] == 10
    assert result[0]["episodeMissingCount"] == 2


def test_missing_subtitles_movies_hits_correct_path(mock_bazarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/movies/wanted"
        return httpx.Response(200, json={"data": [{"radarrId": 2}], "total": 1})

    mock_bazarr(handler)

    assert server.missing_subtitles_movies() == [{"radarrId": 2}]


def test_missing_subtitles_episodes_hits_correct_path(mock_bazarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/episodes/wanted"
        return httpx.Response(200, json={"data": [{"sonarrEpisodeId": 5}], "total": 1})

    mock_bazarr(handler)

    assert server.missing_subtitles_episodes() == [{"sonarrEpisodeId": 5}]


def test_search_movie_subtitles_sends_correct_form(mock_bazarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/movies/subtitles"
        body = request.content.decode()
        assert "radarrid=1" in body
        assert "language=en" in body
        assert "forced=False" in body
        assert "hi=True" in body
        return httpx.Response(204)

    mock_bazarr(handler)

    result = server.search_movie_subtitles(1, "en", hi=True)

    assert "movie 1" in result
    assert "en" in result


def test_search_episode_subtitles_sends_correct_form(mock_bazarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/episodes/subtitles"
        body = request.content.decode()
        assert "seriesid=10" in body
        assert "episodeid=5" in body
        return httpx.Response(204)

    mock_bazarr(handler)

    result = server.search_episode_subtitles(10, 5, "fr")

    assert "episode 5" in result


def test_run_wanted_search_movies(mock_bazarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/system/tasks"
        assert "wanted_search_missing_subtitles_movies" in request.content.decode()
        return httpx.Response(204)

    mock_bazarr(handler)

    assert "movies" in server.run_wanted_search("movies")


def test_run_wanted_search_series(mock_bazarr):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "wanted_search_missing_subtitles_series" in request.content.decode()
        return httpx.Response(204)

    mock_bazarr(handler)

    assert "series" in server.run_wanted_search("series")


def test_run_wanted_search_rejects_invalid_media_type(mock_bazarr):
    mock_bazarr(lambda req: httpx.Response(204))

    with pytest.raises(ValueError):
        server.run_wanted_search("episodes")


def test_system_status_combines_two_endpoints(mock_bazarr):
    def handler(request: httpx.Request) -> httpx.Response:
        payloads = {
            "/api/system/status": {"data": {"bazarr_version": "1.5.1"}},
            "/api/system/health": {"data": [{"issue": "none"}]},
        }
        return httpx.Response(200, json=payloads[request.url.path])

    mock_bazarr(handler)

    result = server.system_status()

    assert result["status"]["bazarr_version"] == "1.5.1"
    assert result["health"] == [{"issue": "none"}]
