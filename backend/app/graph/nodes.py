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
    DeliveryPreparationInput,
    EditorInput,
    FactCheckerInput,
    ReporterInput,
    SpecialCheckInput,
)
from app.agents.delivery import DeliveryPreparationAgent
from app.agents.editor import EditorAgent
from app.agents.fact_checker import FactCheckerAgent
from app.agents.reporter import ReporterAgent
from app.agents.special_check import SpecialCheckAgent
from app.core.llm import LLMClient, OpenAICompatibleClient
from app.core.utils import generate_id, utc_now
from app.graph.state import NewsTaskState
from app.schemas.base import StrictModel
from app.schemas.domain import (
    ErrorInfo,
    ExecutionLogEntry,
    FactCheckReport,
    RevisionRequest,
    SpecialCheckReport,
)
from app.schemas.enums import (
    AgentName,
    AgentStatus,
    ChiefDecision,
    FactCheckOverallResult,
    HumanDecision,
    RevisionTarget,
    SpecialCheckResult,
    TaskStatus,
    WorkflowStage,
)
from app.tools.search import SearchTool, TavilySearchTool


@dataclass(frozen=True)
class WorkflowAgents:
    planning: ChiefPlanningAgent
    reporter: ReporterAgent
    editor: EditorAgent
    fact_checker: FactCheckerAgent
    special_checker: SpecialCheckAgent
    review: ChiefReviewAgent
    delivery_preparer: DeliveryPreparationAgent


def create_default_agents(
    *,
    llm: LLMClient | None = None,
    search: SearchTool | None = None,
) -> WorkflowAgents:
    client = llm or OpenAICompatibleClient()
    search_tool = search or TavilySearchTool()
    return WorkflowAgents(
        planning=ChiefPlanningAgent(llm=client),
        reporter=ReporterAgent(llm=client, search=search_tool),
        editor=EditorAgent(llm=client),
        fact_checker=FactCheckerAgent(llm=client, search=search_tool),
        special_checker=SpecialCheckAgent(),
        review=ChiefReviewAgent(llm=client),
        delivery_preparer=DeliveryPreparationAgent(),
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


def make_nodes(agents: WorkflowAgents, *, max_revision_rounds: int) -> dict[str, Any]:
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
            "task_status": TaskStatus.RUNNING,
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
            "special_check_report": None,
            "delivery_package": None,
            "revision_request": None,
            "task_status": TaskStatus.RUNNING,
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
            "special_check_report": None,
            "delivery_package": None,
            "revision_request": None,
            "task_status": TaskStatus.RUNNING,
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
            "task_status": TaskStatus.RUNNING,
            "current_stage": WorkflowStage.SPECIAL_CHECK,
            "execution_logs": logs,
            "updated_at": utc_now(),
        }

    async def special_check(state: NewsTaskState) -> dict[str, Any]:
        started = utc_now()
        if (
            state.edited_article is None
            or state.article_id is None
            or state.article_version is None
            or state.fact_check_report is None
        ):
            logs = _log(
                state,
                AgentName.SPECIAL_CHECKER,
                AgentStatus.FAILED,
                started,
                error_message="专项检查所需状态不完整",
            )
            return _failed(state, _invalid_state("专项检查所需状态不完整"), logs)

        output = await agents.special_checker.run(
            SpecialCheckInput(
                task_id=state.task_id,
                article_id=state.article_id,
                article=state.edited_article,
                article_version=state.article_version,
                fact_check_report=state.fact_check_report,
                sources=state.research_sources,
            )
        )
        logs = _log(
            state,
            AgentName.SPECIAL_CHECKER,
            output.status,
            started,
            output_summary=output.finding.result.value if output.finding else None,
            error_message=output.error.message if output.error else None,
        )
        if output.status == AgentStatus.FAILED:
            return _failed(state, output.error, logs)

        finding = output.finding
        report = SpecialCheckReport(
            report_id=generate_id("SC"),
            task_id=state.task_id,
            article_id=state.article_id,
            article_version=state.article_version,
            result=finding.result,
            summary=finding.summary,
            issues=finding.issues,
        )
        return {
            "special_check_report": report,
            "task_status": TaskStatus.RUNNING,
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
            or state.special_check_report is None
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
                special_check_report=state.special_check_report,
                revision_round=state.revision_round,
                max_revision_rounds=max_revision_rounds,
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
            update["current_stage"] = WorkflowStage.HUMAN_REVIEW
        elif output.chief_decision in {
            ChiefDecision.REQUEST_EDIT,
            ChiefDecision.REQUEST_RESEARCH,
        }:
            update["revision_round"] = state.revision_round + 1
            update["task_status"] = TaskStatus.RUNNING
            update["current_stage"] = WorkflowStage.REVISION_REQUIRED
            update["delivery_package"] = None
        else:
            update["task_status"] = TaskStatus.RUNNING
            update["current_stage"] = WorkflowStage.PREPARE_DELIVERY
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
                "revision_round": state.revision_round,
                "fact_check_overall": (
                    state.fact_check_report.overall_result.value
                    if state.fact_check_report
                    else None
                ),
                "special_check_result": (
                    state.special_check_report.result.value
                    if state.special_check_report
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
            update["task_status"] = TaskStatus.TERMINATED
            update["current_stage"] = WorkflowStage.TERMINATED
            return update

        if payload.decision == HumanDecision.APPROVE:
            blockers: list[str] = []
            if (
                state.fact_check_report is not None
                and state.fact_check_report.overall_result
                == FactCheckOverallResult.FAILED
            ):
                blockers.append("事实核查未通过")
            if (
                state.special_check_report is not None
                and state.special_check_report.result == SpecialCheckResult.BLOCKED
            ):
                blockers.append("专项检查存在阻断项")
            if blockers:
                update["task_status"] = TaskStatus.HUMAN_REVIEW
                update["current_stage"] = WorkflowStage.HUMAN_REVIEW
                update["review_comments"] = (
                    f"{update.get('review_comments') or state.review_comments or ''}"
                    f"（人工不能覆盖：{'；'.join(blockers)}，无法准备交付）"
                )
                return update
            update["revision_request"] = None
            update["task_status"] = TaskStatus.RUNNING
            update["current_stage"] = WorkflowStage.PREPARE_DELIVERY
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
        update["revision_round"] = state.revision_round + 1
        update["task_status"] = TaskStatus.RUNNING
        update["current_stage"] = WorkflowStage.REVISION_REQUIRED
        update["delivery_package"] = None
        return update

    async def prepare_delivery(state: NewsTaskState) -> dict[str, Any]:
        started = utc_now()
        if (
            state.edited_article is None
            or state.article_id is None
            or state.article_version is None
            or state.fact_check_report is None
            or state.special_check_report is None
        ):
            logs = _log(
                state,
                AgentName.DELIVERY_PREPARER,
                AgentStatus.FAILED,
                started,
                error_message="交付材料所需状态不完整",
            )
            return _failed(state, _invalid_state("交付材料所需状态不完整"), logs)

        try:
            payload = DeliveryPreparationInput(
                task_id=state.task_id,
                article_id=state.article_id,
                article=state.edited_article,
                article_version=state.article_version,
                fact_check_report=state.fact_check_report,
                special_check_report=state.special_check_report,
                sources=state.research_sources,
            )
        except ValueError as exc:
            logs = _log(
                state,
                AgentName.DELIVERY_PREPARER,
                AgentStatus.FAILED,
                started,
                error_message=str(exc),
            )
            return _failed(
                state,
                ErrorInfo(
                    code="DELIVERY_PRECONDITION_FAILED",
                    message=f"交付前置条件未满足：{exc}",
                ),
                logs,
            )

        output = await agents.delivery_preparer.run(payload)
        logs = _log(
            state,
            AgentName.DELIVERY_PREPARER,
            output.status,
            started,
            output_summary="交付材料已准备" if output.package else None,
            error_message=output.error.message if output.error else None,
        )
        if output.status == AgentStatus.FAILED:
            return _failed(state, output.error, logs)
        return {
            "delivery_package": output.package,
            "task_status": TaskStatus.PENDING_REVIEW,
            "current_stage": WorkflowStage.PENDING_REVIEW,
            "execution_logs": logs,
            "updated_at": utc_now(),
        }

    return {
        "chief_planning": chief_planning,
        "reporter": reporter,
        "editor": editor,
        "fact_checker": fact_checker,
        "special_check": special_check,
        "chief_review": chief_review,
        "human_approval": human_approval,
        "prepare_delivery": prepare_delivery,
    }
