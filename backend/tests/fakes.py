from __future__ import annotations

from typing import Any

from app.schemas.domain import (
    ArticleContent,
    EditorialPlan,
    ResearchSource,
    TaskRequirements,
)
from app.tools.search import SearchHit


class FakeLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if not self.responses:
            raise AssertionError("FakeLLM 没有剩余响应")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(user)
        return item


class FakeSearch:
    def __init__(
        self,
        results_by_query: dict[str, list[SearchHit]] | None = None,
        *,
        default: list[SearchHit] | None = None,
        error: BaseException | None = None,
        errors_by_query: dict[str, BaseException] | None = None,
    ) -> None:
        self.results_by_query = results_by_query or {}
        self.default = default or []
        self.error = error
        self.errors_by_query = errors_by_query or {}
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        self.queries.append(query)
        if query in self.errors_by_query:
            raise self.errors_by_query[query]
        if self.error is not None:
            raise self.error
        hits = self.results_by_query.get(query, self.default)
        return hits[:max_results]


def make_plan() -> EditorialPlan:
    return EditorialPlan(
        topic_analysis="分析人工智能在高校教学中的应用现状",
        reporting_angles=["高校教学案例", "应用效果", "现存问题"],
        research_tasks=["搜集高校案例", "查找公开统计数据"],
        article_outline=["背景", "应用现状", "典型案例", "问题", "总结"],
        verification_points=["案例真实性", "统计数据准确性"],
    )


def make_requirements() -> TaskRequirements:
    return TaskRequirements(
        style="客观新闻报道",
        target_length=1500,
        focus=["应用案例", "实际效果"],
    )


def make_article(
    title: str = "人工智能进入高校课堂",
    content: str = "某高校已经开展人工智能教学实践。相关数据显示，试点课程覆盖多个专业。",
) -> ArticleContent:
    return ArticleContent(title=title, content=content)


def make_source(
    source_id: str = "SRC_0001",
    *,
    title: str = "高校人工智能教学案例",
    url: str = "https://example.com/article",
    summary: str = "来源摘要，包含可核查的事实信息。",
) -> ResearchSource:
    return ResearchSource(
        source_id=source_id,
        title=title,
        url=url,
        publisher="示例媒体",
        summary=summary,
    )


def make_hit(
    title: str = "检索到的资料",
    *,
    url: str = "https://search.example.com/a",
    summary: str = "检索结果摘要，包含事实信息。",
) -> SearchHit:
    return SearchHit(title=title, url=url, summary=summary)
