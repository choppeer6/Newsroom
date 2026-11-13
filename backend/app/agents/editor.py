from __future__ import annotations

import logging

from pydantic import Field, field_validator

from app.agents.base import BaseAgent
from app.agents.contracts import EditorInput, EditorOutput
from app.agents.runtime import complete_validated, dump_json, failure, failure_for
from app.core.llm import LLMClient, OpenAICompatibleClient
from app.prompts.loader import load_prompt
from app.schemas.base import StrictModel
from app.schemas.domain import ArticleContent, EditingReport
from app.schemas.enums import AgentName, RevisionTarget

logger = logging.getLogger(__name__)


class EditorPayload(StrictModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    structure_changes: str = Field(min_length=1)
    language_changes: str = Field(min_length=1)
    content_changes: str = Field(min_length=1)

    @field_validator(
        "title",
        "content",
        "structure_changes",
        "language_changes",
        "content_changes",
        mode="before",
    )
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class EditorAgent(BaseAgent[EditorInput, EditorOutput]):
    name = AgentName.EDITOR

    def __init__(self, *, llm: LLMClient | None = None) -> None:
        self._llm = llm or OpenAICompatibleClient()

    async def run(self, payload: EditorInput) -> EditorOutput:
        logger.info("editor start task_id=%s", payload.task_id)
        if (
            payload.revision_request is not None
            and payload.revision_request.target != RevisionTarget.EDITOR
        ):
            return failure(
                EditorOutput,
                "INVALID_REVISION_TARGET",
                "编辑节点只能处理 target=editor 的修改要求",
            )

        try:
            spec = load_prompt("editor", "edit_article")
            result = await complete_validated(
                self._llm,
                spec,
                context={
                    "requirements_json": dump_json(payload.requirements),
                    "draft_json": dump_json(payload.draft),
                    "revision_json": dump_json(payload.revision_request)
                    if payload.revision_request
                    else "",
                    "review_comments": payload.review_comments or "",
                    "fact_check_json": dump_json(payload.fact_check_report)
                    if payload.fact_check_report
                    else "",
                },
                validate=lambda data: EditorPayload.model_validate(data),
            )

            version = payload.current_version + 1
            output = EditorOutput(
                edited_article=ArticleContent(
                    title=result.title,
                    content=result.content,
                ),
                editing_report=EditingReport(
                    structure_changes=result.structure_changes,
                    language_changes=result.language_changes,
                    content_changes=result.content_changes,
                ),
                version=version,
            )
            logger.info(
                "editor completed task_id=%s version=%d",
                payload.task_id,
                version,
            )
            return output
        except Exception as exc:
            output = failure_for(EditorOutput, exc)
            logger.warning(
                "editor failed task_id=%s code=%s",
                payload.task_id,
                output.error.code if output.error else "unknown",
            )
            return output
