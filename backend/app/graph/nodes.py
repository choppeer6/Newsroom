"""Workflow nodes that translate NewsTaskState into agent calls and back."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langgraph.types import interrupt
from pydantic import Field, model_validator

from app.agents.chief_editor import ChiefPlanningAgent, ChiefReviewAgent
from app.agents.contracts import (
    ChiefPlanningInput,
    ChiefReviewInput,
    EditorInput,
    FactCheckerInput,
    PublisherInput,
    ReporterInput,
)
from app.agents.editor import EditorAgent
from app.agents.fact_checker import FactCheckerAgent
from app.agents.publisher import PublisherAgent
from app.agents.reporter import ReporterAgent
from app.core.llm import LLMClient, OpenAICompatibleClient
from app.core.utils import generate_id, utc_now
from app.graph.state import NewsTaskState
from app.schemas.base import StrictModel
from app.schemas.domain import ErrorInfo, ExecutionLogEntry, FactCheckReport, RevisionRequest
from app.schemas.enums import (
    AgentName,
    AgentStatus,
    ChiefDecision,
    HumanDecision,
    RevisionTarget,
    TaskStatus,
    WorkflowStage,
)
from app.services.publish_service import PublishService
from app.tools.search import SearchTool, TavilySearchTool


@dataclass(frozen=True)
class WorkflowAgents:
    planning: ChiefPlanningAgent
    reporter: ReporterAgent
    editor: EditorAgent
    fact_checker: FactCheckerAgent
    review: ChiefReviewAgent
    publisher: PublisherAgent


def create_default_agents(
    *,
    llm: LLMClient | None = None,
    search: SearchTool | None = None,
    publish_service: PublishService | None = None,
) -> WorkflowAgents:
    client = llm or OpenAICompatibleClient()
    search_tool = search or TavilySearchTool()
    return WorkflowAgents(
        planning=ChiefPlanningAgent(llm=client),
        reporter=ReporterAgent(llm=client, search=search_tool),
        editor=EditorAgent(llm=client),
        fact_checker=FactCheckerAgent(llm=client, search=search_tool),
        review=ChiefReviewAgent(llm=client),
        publisher=PublisherAgent(publish_service=publish_service),
    )


class HumanDecisionPayload(StrictModel):
    decision: HumanDecision
    comments: str | None = None
    revision_reason: str | None = None
    revision_requirements: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _revision_fields(self) -> "HumanDecisionPayload":
        if self.decision in {HumanDecision.REQUEST_EDIT, HumanDecision.REQUEST_RESEARCH}:
            if not (self.revision_reason or "").strip():
                raise ValueError("revision_reason is required when requesting a revision")
            if not [item for item in self.revision_requirements if item.strip()]:
                raise ValueError(
                    "revision_requirements is required when requesting a revision"
                )
        return self


class UserConfirmationPayload(StrictModel):
    confirm: bool


def _log(
    state: NewsTaskState,
    agent_name: AgentName,
    status: AgentStatus,
    started_at: datetime,
    *,
    output_summary: str | None = None,
    error_message: str | None = None,
) -> list[ExecutionLogEntry]:
    entry = ExecutionLogEntry(
        log_id=generate_id("LOG"),
        task_id=state.task_id,
        agent_name=agent_name,
        status=status,
        output_summary=output_summary,
        error_message=error_message,
        started_at=started_at,
        finished_at=utc_now(),
    )
    return [*state.execution_logs, entry]


def _failed(
    state: NewsTaskState, error: ErrorInfo | None, logs: list[ExecutionLogEntry]
) -> dict[str, Any]:
    return {
        "task_status": TaskStatus.FAILED,
        "current_stage": WorkflowStage.ERROR,
        "error": error or ErrorInfo(code="WORKFLOW_STATE_INVALID", message="节点缺少必要状态"),
        "execution_logs": logs,
        "updated_at": utc_now(),
    }


def _invalid_state(message: str) -> ErrorInfo:
    return ErrorInfo(code="WORKFLOW_STATE_INVALID", message=message)


def make_nodes(agents: WorkflowAgents, *, max_retry: int) -> dict[str, Any]:
    async def chief_planning(state: NewsTaskState) -> dict[str, Any]:
        started = utc_now()
        output = await agents.planning.run(
            ChiefPlanningInput(
                task_id=state.task_id,
                topic=state.topic,
                description=state.description,
                requirements=state.requirements,
            )
        )
        logs = _log(
            state,
            AgentName.CHIEF_EDITOR,
            output.status,
            started,
            output_summary="采编计划已生成" if output.editorial_plan else None,
            error_message=output.error.message if output.error else None,
        )
        if output.status == AgentStatus.FAILED:
            return _failed(state, output.error, logs)
        return {
            "editorial_plan": output.editorial_plan,
            "task_status": TaskStatus.RESEARCHING,
            "current_stage": WorkflowStage.RESEARCH,
            "execution_logs": logs,
            "updated_at": utc_now(),
        }

    async def reporter(state: NewsTaskState) -> dict[str, Any]:
        started = utc_now()
        revision = (
            state.revision_request
            if state.revision_request
            and state.revision_request.target == RevisionTarget.REPORTER
            else None
        )
        output = await agents.reporter.run(
            ReporterInput(
                task_id=state.task_id,
                editorial_plan=state.editorial_plan,
                requirements=state.requirements,
                revision_request=revision,
                existing_sources=state.research_sources,
                previous_draft=state.edited_article or state.draft_article,
            )
        )
        logs = _log(
            state,
            AgentName.REPORTER,
            output.status,
            started,
            output_summary=f"来源 {len(output.sources)} 条" if output.draft else None,
            error_message=output.error.message if output.error else None,
        )
        if output.status == AgentStatus.FAILED:
            return _failed(state, output.error, logs)
        return {
            "draft_article": output.draft,
            "research_sources": output.sources,
            "research_summary": output.research_summary,
            "unverified_claims": output.unverified_claims,
            "edited_article": None,
            "editing_report": None,
            "fact_check_report": None,
            "revision_request": None,
            "task_status": TaskStatus.EDITING,
            "current_stage": WorkflowStage.EDITING,
            "execution_logs": logs,
            "updated_at": utc_now(),
        }

    async def editor(state: NewsTaskState) -> dict[str, Any]:
        started = utc_now()
        # A fresh reporter draft clears edited_article, so this picks the latest text.
        draft = state.edited_article or state.draft_article
        if draft is None:
            logs = _log(
                state,
                AgentName.EDITOR,
                AgentStatus.FAILED,
                started,
                error_message="没有可编辑的稿件",
            )
            return _failed(state, _invalid_state("没有可编辑的稿件"), logs)

        revision = (
            state.revision_request
            if state.revision_request
            and state.revision_request.target == RevisionTarget.EDITOR
            else None
        )
        output = await agents.editor.run(
            EditorInput(
                task_id=state.task_id,
                draft=draft,
                requirements=state.requirements,
                revision_request=revision,
                review_comments=state.review_comments,
                fact_check_report=state.fact_check_report,
                current_version=state.article_version or 1,
            )
        )
        logs = _log(
            state,
            AgentName.EDITOR,
            output.status,
            started,
            output_summary=f"版本 {output.version}" if output.version else None,
            error_message=output.error.message if output.error else None,
        )
        if output.status == AgentStatus.FAILED:
            return _failed(state, output.error, logs)
        return {
            "edited_article": output.edited_article,
            "editing_report": output.editing_report,
            "article_id": state.article_id or generate_id("ART"),
            "article_version": output.version,
            "fact_check_report": None,
            "revision_request": None,
            "task_status": TaskStatus.FACT_CHECKING,
            "current_stage": WorkflowStage.FACT_CHECK,
            "execution_logs": logs,
            "updated_at": utc_now(),
        }

    async def fact_checker(state: NewsTaskState) -> dict[str, Any]:
        started = utc_now()
        if (
            state.edited_article is None
            or state.article_id is None
            or state.article_version is None
        ):
            logs = _log(
                state,
                AgentName.FACT_CHECKER,
                AgentStatus.FAILED,
                started,
                error_message="缺少待核查稿件",
            )
            return _failed(state, _invalid_state("缺少待核查稿件"), logs)

        output = await agents.fact_checker.run(
            FactCheckerInput(
                task_id=state.task_id,
                article_id=state.article_id,
                article=state.edited_article,
                article_version=state.article_version,
                sources=state.research_sources,
            )
        )
        logs = _log(
            state,
            AgentName.FACT_CHECKER,
            output.status,
            started,
            output_summary=(
                output.verification_report.overall_result.value
                if output.verification_report
                else None
            ),
            error_message=output.error.message if output.error else None,
        )
        if output.status == AgentStatus.FAILED:
            return _failed(state, output.error, logs)

        finding = output.verification_report
        report = FactCheckReport(
            report_id=generate_id("FC"),
            article_id=state.article_id,
            article_version=state.article_version,
            overall_result=finding.overall_result,
            claims=finding.claims,
            issues=finding.issues,
            recommendation=finding.recommendation,
        )
        return {
            "fact_check_report": report,
            "task_status": TaskStatus.REVIEWING,
            "current_stage": WorkflowStage.CHIEF_REVIEW,
            "execution_logs": logs,
            "updated_at": utc_now(),
        }

    async def chief_review(state: NewsTaskState) -> dict[str, Any]:
        started = utc_now()
        if (
            state.editorial_plan is None
            or state.edited_article is None
            or state.article_id is None
            or state.article_version is None
            or state.fact_check_report is None
        ):
            logs = _log(
                state,
                AgentName.CHIEF_EDITOR,
                AgentStatus.FAILED,
                started,
                error_message="审核所需状态不完整",
            )
            return _failed(state, _invalid_state("审核所需状态不完整"), logs)

        output = await agents.review.run(
            ChiefReviewInput(
                task_id=state.task_id,
                topic=state.topic,
                description=state.description,
                requirements=state.requirements,
                editorial_plan=state.editorial_plan,
                sources=state.research_sources,
                edited_article=state.edited_article,
                article_id=state.article_id,
                article_version=state.article_version,
                fact_check_report=state.fact_check_report,
                retry_count=state.retry_count,
                max_retry=max_retry,
            )
        )
        logs = _log(
            state,
            AgentName.CHIEF_EDITOR,
            output.status,
            started,
            output_summary=output.chief_decision.value if output.chief_decision else None,
            error_message=output.error.message if output.error else None,
        )
        if output.status == AgentStatus.FAILED:
            return _failed(state, output.error, logs)

        update: dict[str, Any] = {
            "chief_decision": output.chief_decision,
            "review_comments": output.review_comments,
            "revision_request": output.revision_request,
            "execution_logs": logs,
            "updated_at": utc_now(),
        }
        if output.chief_decision == ChiefDecision.HUMAN_REVIEW:
            update["task_status"] = TaskStatus.HUMAN_REVIEW
            update["current_stage"] = WorkflowStage.HUMAN_APPROVAL
        elif output.chief_decision in {
            ChiefDecision.REQUEST_EDIT,
            ChiefDecision.REQUEST_RESEARCH,
        }:
            update["retry_count"] = state.retry_count + 1
            update["task_status"] = TaskStatus.REVISION_REQUIRED
            update["current_stage"] = WorkflowStage.REVISION_REQUIRED
        return update

    async def human_approval(state: NewsTaskState) -> dict[str, Any]:
        answer = interrupt(
            {
                "task_id": state.task_id,
                "article_id": state.article_id,
                "article_version": state.article_version,
                "title": state.edited_article.title if state.edited_article else None,
                "chief_decision": (
                    state.chief_decision.value if state.chief_decision else None
                ),
                "review_comments": state.review_comments,
                "fact_check_overall": (
                    state.fact_check_report.overall_result.value
                    if state.fact_check_report
                    else None
                ),
            }
        )
        payload = HumanDecisionPayload.model_validate(answer)
        update: dict[str, Any] = {
            "human_decision": payload.decision,
            "updated_at": utc_now(),
        }
        if payload.comments:
            update["review_comments"] = payload.comments

        if payload.decision == HumanDecision.TERMINATE:
            update["task_status"] = TaskStatus.CANCELLED
            update["current_stage"] = WorkflowStage.CANCELLED
            return update

        if payload.decision == HumanDecision.APPROVE:
            update["revision_request"] = None
            return update

        target = (
            RevisionTarget.EDITOR
            if payload.decision == HumanDecision.REQUEST_EDIT
            else RevisionTarget.REPORTER
        )
        update["revision_request"] = RevisionRequest(
            target=target,
            reason=payload.revision_reason or "",
            requirements=payload.revision_requirements,
        )
        update["retry_count"] = state.retry_count + 1
        update["task_status"] = TaskStatus.REVISION_REQUIRED
        update["current_stage"] = WorkflowStage.REVISION_REQUIRED
        return update

    async def publisher(state: NewsTaskState) -> dict[str, Any]:
        started = utc_now()
        if (
            state.edited_article is None
            or state.article_id is None
            or state.article_version is None
            or state.fact_check_report is None
        ):
            logs = _log(
                state,
                AgentName.PUBLISHER,
                AgentStatus.FAILED,
                started,
                error_message="发布所需状态不完整",
            )
            return _failed(state, _invalid_state("发布所需状态不完整"), logs)

        output = await agents.publisher.run(
            PublisherInput(
                task_id=state.task_id,
                article_id=state.article_id,
                article=state.edited_article,
                article_version=state.article_version,
                chief_decision=ChiefDecision.APPROVE,
                fact_check_status=state.fact_check_report.overall_result,
                user_confirmation=False,
            )
        )
        logs = _log(
            state,
            AgentName.PUBLISHER,
            output.status,
            started,
            output_summary="待发布" if output.publication else None,
            error_message=output.error.message if output.error else None,
        )
        if output.status == AgentStatus.FAILED:
            return _failed(state, output.error, logs)
        return {
            "publication": output.publication,
            "task_status": TaskStatus.PENDING_PUBLISH,
            "current_stage": WorkflowStage.PENDING_PUBLISH,
            "execution_logs": logs,
            "updated_at": utc_now(),
        }

    async def user_confirmation(state: NewsTaskState) -> dict[str, Any]:
        answer = interrupt(
            {
                "task_id": state.task_id,
                "article_id": state.article_id,
                "article_version": state.article_version,
                "publication": (
                    state.publication.model_dump(mode="json")
                    if state.publication
                    else None
                ),
            }
        )
        payload = UserConfirmationPayload.model_validate(answer)
        return {"user_confirmation": payload.confirm, "updated_at": utc_now()}

    async def publish(state: NewsTaskState) -> dict[str, Any]:
        started = utc_now()
        if (
            state.edited_article is None
            or state.article_id is None
            or state.article_version is None
            or state.fact_check_report is None
        ):
            logs = _log(
                state,
                AgentName.PUBLISHER,
                AgentStatus.FAILED,
                started,
                error_message="发布所需状态不完整",
            )
            return _failed(state, _invalid_state("发布所需状态不完整"), logs)

        output = await agents.publisher.run(
            PublisherInput(
                task_id=state.task_id,
                article_id=state.article_id,
                article=state.edited_article,
                article_version=state.article_version,
                chief_decision=ChiefDecision.APPROVE,
                fact_check_status=state.fact_check_report.overall_result,
                user_confirmation=True,
            )
        )
        logs = _log(
            state,
            AgentName.PUBLISHER,
            output.status,
            started,
            output_summary=(
                output.publication.status.value if output.publication else None
            ),
            error_message=output.error.message if output.error else None,
        )
        if output.status == AgentStatus.FAILED:
            return {
                "publication": output.publication,
                "task_status": TaskStatus.PENDING_PUBLISH,
                "current_stage": WorkflowStage.PENDING_PUBLISH,
                "error": output.error,
                "execution_logs": logs,
                "updated_at": utc_now(),
            }
        return {
            "publication": output.publication,
            "task_status": TaskStatus.PUBLISHED,
            "current_stage": WorkflowStage.PUBLISHED,
            "error": None,
            "execution_logs": logs,
            "updated_at": utc_now(),
        }

    return {
        "chief_planning": chief_planning,
        "reporter": reporter,
        "editor": editor,
        "fact_checker": fact_checker,
        "chief_review": chief_review,
        "human_approval": human_approval,
        "publisher": publisher,
        "user_confirmation": user_confirmation,
        "publish": publish,
    }
