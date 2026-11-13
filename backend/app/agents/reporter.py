from __future__ import annotations

import asyncio
import logging

from pydantic import Field, field_validator

from app.agents.base import BaseAgent
from app.agents.contracts import ReporterInput, ReporterOutput
from app.agents.runtime import complete_validated, dump_json, failure, failure_for
from app.agents.sources import dedupe_strings, merge_sources
from app.core.llm import LLMClient, OpenAICompatibleClient
from app.prompts.loader import load_prompt
from app.schemas.base import StrictModel
from app.schemas.domain import ArticleContent, ResearchSource
from app.schemas.enums import AgentName
from app.tools.search import SearchHit, SearchTool, TavilySearchTool

logger = logging.getLogger(__name__)

SEARCH_RESULTS_PER_QUERY = 4
MAX_QUERIES = 8
MAX_SOURCES = 12
SEARCH_CONCURRENCY = 3


class QueryPayload(StrictModel):
    queries: list[str] = Field(min_length=1)

    @field_validator("queries", mode="before")
    @classmethod
    def _trim(cls, value: object) -> object:
        if isinstance(value, list):
            return [item.strip() for item in value if isinstance(item, str)]
        return value

    @field_validator("queries")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        cleaned = dedupe_strings(value)
        if not cleaned:
            raise ValueError("queries must not be empty")
        return cleaned[:MAX_QUERIES]


class DraftPayload(StrictModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    research_summary: str = Field(min_length=1)
    unverified_claims: list[str] = Field(default_factory=list)

    @field_validator("title", "content", "research_summary", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ReporterAgent(BaseAgent[ReporterInput, ReporterOutput]):
    name = AgentName.REPORTER

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        search: SearchTool | None = None,
    ) -> None:
        self._llm = llm or OpenAICompatibleClient()
        self._search = search or TavilySearchTool()

    async def run(self, payload: ReporterInput) -> ReporterOutput:
        logger.info("reporter start task_id=%s", payload.task_id)
        try:
            sources = await self._collect_sources(payload)
            if not sources:
                return failure(
                    ReporterOutput,
                    "SEARCH_EMPTY",
                    "检索未返回任何可用来源",
                    retryable=True,
                )

            draft = await self._write_draft(payload, sources)
            output = ReporterOutput(
                draft=ArticleContent(title=draft.title, content=draft.content),
                sources=sources,
                research_summary=draft.research_summary,
                unverified_claims=dedupe_strings(draft.unverified_claims),
            )
            logger.info(
                "reporter completed task_id=%s sources=%d",
                payload.task_id,
                len(sources),
            )
            return output
        except Exception as exc:
            output = failure_for(ReporterOutput, exc)
            logger.warning(
                "reporter failed task_id=%s code=%s",
                payload.task_id,
                output.error.code if output.error else "unknown",
            )
            return output

    async def _collect_sources(
        self, payload: ReporterInput
    ) -> list[ResearchSource]:
        spec = load_prompt("reporter", "search_queries")
        existing_brief = [
            {
                "source_id": source.source_id,
                "title": source.title,
                "url": source.url,
            }
            for source in payload.existing_sources
        ]
        queries = await complete_validated(
            self._llm,
            spec,
            context={
                "plan_json": dump_json(payload.editorial_plan),
                "revision_json": dump_json(payload.revision_request)
                if payload.revision_request
                else "",
                "existing_sources_json": dump_json(existing_brief)
                if existing_brief
                else "",
            },
            validate=lambda data: QueryPayload.model_validate(data),
        )

        hits = await self._search_all(queries.queries)
        return merge_sources(
            payload.existing_sources,
            hits,
            prefix="SRC",
            limit=MAX_SOURCES,
        )

    async def _search_all(self, queries: list[str]) -> list[SearchHit]:
        semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def search_one(query: str):
            async with semaphore:
                return await self._search.search(
                    query, max_results=SEARCH_RESULTS_PER_QUERY
                )

        batches = await asyncio.gather(*(search_one(item) for item in queries))
        return [hit for batch in batches for hit in batch]

    async def _write_draft(
        self, payload: ReporterInput, sources: list[ResearchSource]
    ) -> DraftPayload:
        spec = load_prompt("reporter", "write_draft")
        sources_brief = [
            {
                "source_id": source.source_id,
                "title": source.title,
                "url": source.url,
                "summary": source.summary,
                "published_at": source.published_at.isoformat()
                if source.published_at
                else None,
            }
            for source in sources
        ]
        return await complete_validated(
            self._llm,
            spec,
            context={
                "requirements_json": dump_json(payload.requirements),
                "plan_json": dump_json(payload.editorial_plan),
                "sources_json": dump_json(sources_brief),
                "revision_json": dump_json(payload.revision_request)
                if payload.revision_request
                else "",
                "previous_draft_json": dump_json(payload.previous_draft)
                if payload.previous_draft
                else "",
            },
            validate=lambda data: DraftPayload.model_validate(data),
        )
