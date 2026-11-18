from __future__ import annotations

import logging

from pydantic import Field, field_validator, model_validator

from app.agents.base import BaseAgent
from app.agents.contracts import (
    ChiefPlanningInput,
    ChiefPlanningOutput,
    ChiefReviewInput,
    ChiefReviewOutput,
)
from app.agents.runtime import complete_validated, dump_json, failure_for
from app.agents.sources import dedupe_strings
from app.core.llm import LLMClient, OpenAICompatibleClient
from app.prompts.loader import load_prompt
from app.schemas.base import StrictModel
from app.schemas.domain import EditorialPlan, RevisionRequest
from app.schemas.enums import (
    AgentName,
    ChiefDecision,
    FactCheckOverallResult,
    RevisionTarget,
)

logger = logging.getLogger(__name__)

_REVISION_DECISIONS = {
    ChiefDecision.REQUEST_EDIT,
    ChiefDecision.REQUEST_RESEARCH,
}


def _clean_list(value: object) -> object:
    if isinstance(value, list):
        return dedupe_strings(
            [item.strip() for item in value if isinstance(item, str) and item.strip()]
        )
    return value


class PlanPayload(StrictModel):
    topic_analysis: str = Field(min_length=1)
    reporting_angles: list[str] = Field(min_length=1)
    research_tasks: list[str] = Field(min_length=1)
    article_outline: list[str] = Field(min_length=1)
    verification_points: list[str] = Field(min_length=1)

    @field_validator("topic_analysis", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "reporting_angles",
        "research_tasks",
        "article_outline",
        "verification_points",
        mode="before",
    )
    @classmethod
    def _clean_items(cls, value: object) -> object:
        return _clean_list(value)

    @model_validator(mode="after")
    def _lists_not_empty(self) -> "PlanPayload":
        for name in (
            "reporting_angles",
            "research_tasks",
            "article_outline",
            "verification_points",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        return self


class ReviewPayload(StrictModel):
    chief_decision: ChiefDecision
    review_comments: str = Field(min_length=1)
    revision_reason: str | None = None
    revision_requirements: list[str] = Field(default_factory=list)
    related_claims: list[str] = Field(default_factory=list)

    @field_validator("review_comments", mode="before")
    @classmethod
    def _strip_comments(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("revision_reason", mode="before")
    @classmethod
    def _strip_reason(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("revision_requirements", "related_claims", mode="before")
    @classmethod
    def _clean_items(cls, value: object) -> object:
        return _clean_list(value)

    @model_validator(mode="after")
    def _revision_fields(self) -> "ReviewPayload":
        if self.chief_decision in _REVISION_DECISIONS:
            if not self.revision_reason:
                raise ValueError(
                    "revision_reason is required when the decision requests a revision"
                )
            if not self.revision_requirements:
                raise ValueError(
                    "revision_requirements is required when the decision requests a revision"
                )
        return self


def apply_review_constraints(
    payload: ReviewPayload, payload_input: ChiefReviewInput
) -> tuple[ChiefDecision, str, RevisionRequest | None]:
    """Downgrade unsafe model decisions; targets and loop caps stay in code."""
    decision = payload.chief_decision
    notes: list[str] = []

    if (
        decision == ChiefDecision.APPROVE
        and payload_input.fact_check_report.overall_result
        != FactCheckOverallResult.PASSED
    ):
        notes.append("事实核查未全部通过，系统已转为人工审核")
        decision = ChiefDecision.HUMAN_REVIEW

    if (
        decision in _REVISION_DECISIONS
        and payload_input.retry_count >= payload_input.max_retry
    ):
        notes.append(
            f"退回次数已达上限（{payload_input.max_retry}），系统已转为人工审核"
        )
        decision = ChiefDecision.HUMAN_REVIEW

    comments = payload.review_comments
    if notes:
        comments = f"{comments}（{'；'.join(notes)}）"

    revision: RevisionRequest | None = None
    if decision == ChiefDecision.REQUEST_EDIT:
        revision = RevisionRequest(
            target=RevisionTarget.EDITOR,
            reason=payload.revision_reason or "",
            requirements=payload.revision_requirements,
            related_claims=payload.related_claims,
        )
    elif decision == ChiefDecision.REQUEST_RESEARCH:
        revision = RevisionRequest(
            target=RevisionTarget.REPORTER,
            reason=payload.revision_reason or "",
            requirements=payload.revision_requirements,
            related_claims=payload.related_claims,
        )
    return decision, comments, revision


class ChiefPlanningAgent(BaseAgent[ChiefPlanningInput, ChiefPlanningOutput]):
    name = AgentName.CHIEF_EDITOR

    def __init__(self, *, llm: LLMClient | None = None) -> None:
        self._llm = llm or OpenAICompatibleClient()

    async def run(self, payload: ChiefPlanningInput) -> ChiefPlanningOutput:
        logger.info("chief_planning start task_id=%s", payload.task_id)
        try:
            spec = load_prompt("chief_editor", "planning")
            result = await complete_validated(
                self._llm,
                spec,
                context={
                    "topic": payload.topic,
                    "description": payload.description,
                    "requirements_json": dump_json(payload.requirements),
                },
                validate=lambda data: PlanPayload.model_validate(data),
            )
            plan = EditorialPlan(
                topic_analysis=result.topic_analysis,
                reporting_angles=result.reporting_angles,
                research_tasks=result.research_tasks,
                article_outline=result.article_outline,
                verification_points=result.verification_points,
            )
            logger.info(
                "chief_planning completed task_id=%s angles=%d",
                payload.task_id,
                len(plan.reporting_angles),
            )
            return ChiefPlanningOutput(editorial_plan=plan)
        except Exception as exc:
            output = failure_for(ChiefPlanningOutput, exc)
            logger.warning(
                "chief_planning failed task_id=%s code=%s",
                payload.task_id,
                output.error.code if output.error else "unknown",
            )
            return output


class ChiefReviewAgent(BaseAgent[ChiefReviewInput, ChiefReviewOutput]):
    name = AgentName.CHIEF_EDITOR

    def __init__(self, *, llm: LLMClient | None = None) -> None:
        self._llm = llm or OpenAICompatibleClient()

    async def run(self, payload: ChiefReviewInput) -> ChiefReviewOutput:
        logger.info(
            "chief_review start task_id=%s article_id=%s version=%d retry=%d/%d",
            payload.task_id,
            payload.article_id,
            payload.article_version,
            payload.retry_count,
            payload.max_retry,
        )
        try:
            spec = load_prompt("chief_editor", "review")
            result = await complete_validated(
                self._llm,
                spec,
                context={
                    "topic": payload.topic,
                    "description": payload.description,
                    "requirements_json": dump_json(payload.requirements),
                    "plan_json": dump_json(payload.editorial_plan),
                    "article_json": dump_json(payload.edited_article),
                    "article_version": payload.article_version,
                    "sources_json": dump_json(
                        [
                            {
                                "source_id": source.source_id,
                                "title": source.title,
                                "url": source.url,
                            }
                            for source in payload.sources
                        ]
                    ),
                    "fact_check_json": dump_json(payload.fact_check_report),
                    "retry_count": payload.retry_count,
                    "max_retry": payload.max_retry,
                },
                validate=lambda data: ReviewPayload.model_validate(data),
            )
            decision, comments, revision = apply_review_constraints(
                result, payload_input=payload
            )
            output = ChiefReviewOutput(
                chief_decision=decision,
                review_comments=comments,
                revision_request=revision,
            )
            logger.info(
                "chief_review completed task_id=%s decision=%s",
                payload.task_id,
                decision,
            )
            return output
        except Exception as exc:
            output = failure_for(ChiefReviewOutput, exc)
            logger.warning(
                "chief_review failed task_id=%s code=%s",
                payload.task_id,
                output.error.code if output.error else "unknown",
            )
            return output
