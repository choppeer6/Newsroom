"""In-process workflow runner backing the temporary demo console."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.utils import generate_id
from app.graph.state import NewsTaskState
from app.graph.workflow import NewsroomWorkflow, WorkflowResult
from app.schemas.domain import TaskRequirements
from app.schemas.enums import HumanDecision, TaskStatus, WorkflowStage

logger = logging.getLogger(__name__)

_REVISION_DECISIONS = {HumanDecision.REQUEST_EDIT, HumanDecision.REQUEST_RESEARCH}


@dataclass
class DemoJob:
    task_id: str
    state: NewsTaskState
    running: bool = True
    error: str | None = None
    interrupt: dict[str, Any] | None = None
    handle: asyncio.Task[None] | None = None


class DemoService:
    def __init__(self, *, workflow: NewsroomWorkflow | None = None) -> None:
        self._workflow = workflow
        self._jobs: dict[str, DemoJob] = {}

    @property
    def workflow(self) -> NewsroomWorkflow:
        if self._workflow is None:
            self._workflow = NewsroomWorkflow()
        return self._workflow

    def meta(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "llm_configured": settings.llm_api_key is not None,
            "search_configured": settings.search_api_key is not None,
            "llm_model": settings.llm_model,
            "search_provider": settings.search_provider,
            "max_revision_rounds": settings.max_revision_rounds,
        }

    def start(
        self,
        *,
        topic: str,
        description: str,
        requirements: TaskRequirements,
    ) -> DemoJob:
        task_id = generate_id("DEMO")
        state = NewsTaskState(
            task_id=task_id,
            topic=topic,
            description=description,
            requirements=requirements,
        )
        job = DemoJob(task_id=task_id, state=state)
        self._jobs[task_id] = job
        job.handle = asyncio.create_task(self._run(job, state))
        return job

    def submit_review(
        self,
        task_id: str,
        *,
        decision: HumanDecision,
        comments: str | None,
        revision_reason: str | None,
        revision_requirements: list[str],
    ) -> DemoJob:
        job = self._waiting_job(task_id)
        value: dict[str, Any] = {"decision": decision.value}
        if comments:
            value["comments"] = comments
        if decision in _REVISION_DECISIONS:
            value["revision_reason"] = revision_reason or ""
            value["revision_requirements"] = revision_requirements
        self._resume(job, value)
        return job

    def submit_delivery(self, task_id: str, *, confirm: bool) -> DemoJob:
        job = self._get(task_id)
        if job.running:
            raise ConflictError("任务仍在执行，请等待当前步骤结束")
        if job.state.task_status != TaskStatus.PENDING_REVIEW:
            raise ConflictError("当前任务不在待复核环节")
        if confirm:
            job.state.task_status = TaskStatus.DELIVERED
            job.state.current_stage = WorkflowStage.DELIVERED
            job.state.touch()
        return job

    def snapshot(self, task_id: str) -> dict[str, Any]:
        job = self._get(task_id)
        state = job.state
        article = state.edited_article or state.draft_article
        report = state.fact_check_report
        special = state.special_check_report
        package = state.delivery_package
        return {
            "task_id": state.task_id,
            "topic": state.topic,
            "phase": self._phase(job),
            "task_status": state.task_status.value,
            "current_stage": state.current_stage.value,
            "paused": state.paused,
            "revision_round": state.revision_round,
            "max_revision_rounds": get_settings().max_revision_rounds,
            "updated_at": state.updated_at.isoformat(),
            "interrupt": job.interrupt,
            "plan": state.editorial_plan.model_dump(mode="json")
            if state.editorial_plan
            else None,
            "article": (
                {
                    "article_id": state.article_id,
                    "version": state.article_version,
                    "title": article.title,
                    "content": article.content,
                }
                if article
                else None
            ),
            "sources": [
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "url": source.url,
                    "publisher": source.publisher,
                }
                for source in state.research_sources
            ],
            "research_summary": state.research_summary,
            "unverified_claims": state.unverified_claims,
            "fact_check": (
                {
                    "report_id": report.report_id,
                    "article_version": report.article_version,
                    "overall_result": report.overall_result.value,
                    "issues": report.issues,
                    "claims": [
                        {
                            "claim": claim.claim,
                            "result": claim.result.value,
                            "reason": claim.reason,
                        }
                        for claim in report.claims
                    ],
                }
                if report
                else None
            ),
            "special_check": (
                {
                    "report_id": special.report_id,
                    "article_version": special.article_version,
                    "result": special.result.value,
                    "summary": special.summary,
                    "issues": [
                        issue.model_dump(mode="json") for issue in special.issues
                    ],
                }
                if special
                else None
            ),
            "chief": {
                "decision": state.chief_decision.value if state.chief_decision else None,
                "comments": state.review_comments,
            },
            "revision": state.revision_request.model_dump(mode="json")
            if state.revision_request
            else None,
            "delivery": (
                {
                    "package_id": package.package_id,
                    "article_version": package.article_version,
                    "prepared_at": package.prepared_at.isoformat(),
                    "note": package.note,
                }
                if package
                else None
            ),
            "logs": [
                {
                    "agent": entry.agent_name.value,
                    "status": entry.status.value,
                    "started_at": entry.started_at.isoformat(),
                    "finished_at": entry.finished_at.isoformat()
                    if entry.finished_at
                    else None,
                    "error": entry.error_message,
                }
                for entry in state.execution_logs
            ],
            "error": state.error.model_dump(mode="json")
            if state.error
            else ({"code": "RUNTIME_ERROR", "message": job.error, "retryable": False}
                  if job.error
                  else None),
        }

    async def _run(self, job: DemoJob, state: NewsTaskState) -> None:
        try:
            self._apply(job, await self.workflow.run(state))
        except Exception as exc:
            logger.exception("demo task crashed task_id=%s", job.task_id)
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.running = False

    async def _continue(self, job: DemoJob, value: Any) -> None:
        try:
            self._apply(job, await self.workflow.resume(job.task_id, value))
        except Exception as exc:
            logger.exception("demo resume crashed task_id=%s", job.task_id)
            job.error = f"{type(exc).__name__}: {exc}"
        finally:
            job.running = False

    def _resume(self, job: DemoJob, value: Any) -> None:
        job.running = True
        job.error = None
        job.handle = asyncio.create_task(self._continue(job, value))

    @staticmethod
    def _apply(job: DemoJob, result: WorkflowResult) -> None:
        job.state = result.state
        job.interrupt = result.interrupt

    @staticmethod
    def _phase(job: DemoJob) -> str:
        if job.running:
            return "running"
        if job.error or job.state.task_status == TaskStatus.FAILED:
            return "failed"
        if job.interrupt is not None:
            return "human_review"
        if job.state.task_status == TaskStatus.PENDING_REVIEW:
            return "pending_review"
        if job.state.task_status == TaskStatus.DELIVERED:
            return "delivered"
        if job.state.task_status == TaskStatus.TERMINATED:
            return "terminated"
        return "finished"

    def _waiting_job(self, task_id: str) -> DemoJob:
        job = self._get(task_id)
        if job.running:
            raise ConflictError("任务仍在执行，请等待当前步骤结束")
        if job.interrupt is None:
            raise ConflictError("任务当前不在等待人工输入")
        return job

    def _get(self, task_id: str) -> DemoJob:
        job = self._jobs.get(task_id)
        if job is None:
            raise NotFoundError(f"任务不存在: {task_id}")
        return job
