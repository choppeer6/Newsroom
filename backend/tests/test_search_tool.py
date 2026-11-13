import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.tools.search import SearchError, SearchNotConfiguredError, TavilySearchTool


def make_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "search_provider": "tavily",
        "search_api_key": "tvly-test",
    }
    values.update(overrides)
    return Settings(**values)


def test_search_maps_results_and_respects_limit():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "结果一",
                        "url": "https://one.example.com/a",
                        "content": "内容一",
                        "published_date": "2026-01-01T08:00:00Z",
                    },
                    {
                        "title": "结果二",
                        "url": "https://two.example.com/b",
                        "content": "内容二",
                    },
                    {
                        "title": "结果三",
                        "url": "https://three.example.com/c",
                        "content": "内容三",
                    },
                ]
            },
        )

    client = TavilySearchTool(
        make_settings(), transport=httpx.MockTransport(handler)
    )

    hits = asyncio.run(client.search("高校人工智能", max_results=2))

    assert [hit.title for hit in hits] == ["结果一", "结果二"]
    assert hits[0].published_at is not None
    assert hits[0].published_at.year == 2026
    body = json.loads(requests[0].content)
    assert body["api_key"] == "tvly-test"
    assert body["query"] == "高校人工智能"
    assert body["max_results"] == 2


def test_search_skips_invalid_urls_and_truncates_summary():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "非法", "url": "ftp://bad.example.com/a", "content": "x"},
                    {
                        "title": "合法",
                        "url": "https://ok.example.com/a",
                        "content": "长" * 900,
                    },
                ]
            },
        )

    client = TavilySearchTool(
        make_settings(), transport=httpx.MockTransport(handler)
    )

    hits = asyncio.run(client.search("查询"))

    assert len(hits) == 1
    assert hits[0].url == "https://ok.example.com/a"
    assert len(hits[0].summary) == 600


def test_search_requires_api_key():
    client = TavilySearchTool(make_settings(search_api_key=""))

    with pytest.raises(SearchNotConfiguredError):
        asyncio.run(client.search("查询"))


def test_search_maps_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "temporary"})

    client = TavilySearchTool(
        make_settings(), transport=httpx.MockTransport(handler)
    )

    with pytest.raises(SearchError) as exc_info:
        asyncio.run(client.search("查询"))

    assert exc_info.value.retryable is True


def test_search_rejects_malformed_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": []})

    client = TavilySearchTool(
        make_settings(), transport=httpx.MockTransport(handler)
    )

    with pytest.raises(SearchError) as exc_info:
        asyncio.run(client.search("查询"))

    assert exc_info.value.retryable is False
