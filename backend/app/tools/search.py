"""Search tool used by Reporter and Fact Checker agents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings

TAVILY_ENDPOINT = "https://api.tavily.com/search"
_MAX_SUMMARY_CHARS = 600
_MAX_TITLE_CHARS = 300


class SearchError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


class SearchNotConfiguredError(SearchError):
    def __init__(self) -> None:
        super().__init__("尚未配置 SEARCH_API_KEY", retryable=False)


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    summary: str
    published_at: datetime | None = None


class SearchTool(Protocol):
    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]: ...


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


class TavilySearchTool:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport
        self._timeout = timeout

    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        if self._settings.search_api_key is None:
            raise SearchNotConfiguredError()

        payload = {
            "api_key": self._settings.search_api_key.get_secret_value(),
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        # trust_env=False keeps a malformed local HTTP_PROXY from breaking API calls.
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            trust_env=False,
        ) as client:
            try:
                response = await client.post(TAVILY_ENDPOINT, json=payload)
            except httpx.HTTPError as exc:
                raise SearchError(
                    f"搜索服务请求失败：{type(exc).__name__}", retryable=True
                ) from exc

        if response.status_code >= 400:
            raise SearchError(
                f"搜索服务返回 HTTP {response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise SearchError("搜索服务返回非 JSON 数据", retryable=False) from exc

        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise SearchError("搜索服务响应缺少 results 字段", retryable=False)

        hits: list[SearchHit] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                continue
            title = str(item.get("title") or url).strip()
            summary = str(item.get("content") or "").strip()
            hits.append(
                SearchHit(
                    title=title[:_MAX_TITLE_CHARS],
                    url=url,
                    summary=summary[:_MAX_SUMMARY_CHARS],
                    published_at=_parse_datetime(item.get("published_date")),
                )
            )
            if len(hits) >= max_results:
                break
        return hits
