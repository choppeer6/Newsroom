"""Background task execution service for the formal task API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.errors import BusyError, ConflictError
from app.core.utils import generate_id
from app.graph.state import NewsTaskState
from app.graph.workflow import NewsroomWorkflow, state_from_values
from app.schemas.domain import ArticleContent, DeliveryPackage, ErrorInfo, ExecutionLogEntry
from app.schemas.enums import HumanDecision, TaskStatus, WorkflowStage
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)

_REVISION_DECISIONS = {HumanDecision.REQUEST_EDIT, HumanDecision.REQUEST_RESEARCH}


@dataclass
class ExecutionJob:
    task_id: str
    latest_state: NewsTaskState
    pause_requested: bool = False
    handle: asyncio.Task[None] | None = field(default=None)


class ExecutionService:
    def __init__(
        self,
        tasks: TaskService,
        *,
        workflow: NewsroomWorkflow | None = None,
        lock_ttl_seconds: int | None = None,
    ) -> None:
        self._tasks = tasks
        self._workflow = workflow
        self._lock_ttl = (
            get_settings().execution_lock_ttl_seconds
            if lock_ttl_seconds is None
            else lock_ttl_seconds
        )
        self._jobs: dict[str, ExecutionJob] = {}

    @property
    def workflow(self) -> NewsroomWorkflow:
        if self._workflow is None:
            self._workflow = NewsroomWorkflow()
        return self._workflow

    def is_running(self, task_id: str) -> bool:
        job = self._jobs.get(task_id)
        return job is not None and job.handle is not None and not job.handle.done()

    async def execute(self, task_id: str) -> NewsTaskState:
        state = await self._tasks.get_task(task_id)
        await self._ensure_idle(task_id)
        if state.paused:
            raise ConflictError("任务已暂停，请先恢复")
        if state.task_status == TaskStatus.RUNNING:
            raise ConflictError("任务正在执行")
        if state.task_status != TaskStatus.CREATED:
            raise ConflictError(f"任务状态 {state.task_status} 不允许执行")

        token = await self._acquire(task_id)
        state.task_status = TaskStatus.RUNNING
        state.current_stage = WorkflowStage.CHIEF_PLANNING
        state.paused = False
        state.error = None
        state.touch()
        await self._tasks.save_state(state)
        self._start_job(
            state, token, lambda: self.workflow.stream(state)
        )
        return state

    async def pause(self, task_id: str) -> NewsTaskState:
        state = await self._tasks.get_task(task_id)
        if state.task_status not in {TaskStatus.CREATED, TaskStatus.RUNNING}:
            raise ConflictError(f"任务状态 {state.task_status} 不允许暂停")
        if state.paused:
            return state

        job = self._jobs.get(task_id)
        if job is not None and job.handle is not None and not job.handle.done():
            job.pause_requested = True
            latest = job.latest_state
            latest.paused = True
            latest.touch()
            await self._tasks.save_state(latest)
            return latest

        if state.task_status != TaskStatus.CREATED:
            raise ConflictError("任务当前未在执行，无法暂停")
        state.paused = True
        state.touch()
        await self._tasks.save_state(state)
        return state

    async def resume(self, task_id: str) -> NewsTaskState:
        state = await self._tasks.get_task(task_id)
        await self._ensure_idle(task_id, wait=True)
        if not state.paused:
            raise ConflictError("任务未处于暂停状态")

        if state.task_status == TaskStatus.CREATED:
            state.paused = False
            await self._tasks.save_state(state)
            return await self.execute(task_id)

        if state.task_status == TaskStatus.RUNNING:
            if not await self.workflow.has_next_step(task_id):
                raise ConflictError("任务没有可恢复的执行检查点")
            token = await self._acquire(task_id)
            state.paused = False
            state.task_status = TaskStatus.RUNNING
            state.touch()
            await self._tasks.save_state(state)
            self._start_job(
                state,
                token,
                lambda: self.workflow.stream_continue(task_id),
            )
            return state

        raise ConflictError(f"任务状态 {state.task_status} 不允许恢复")

    async def submit_human_review(
        self,
        task_id: str,
        *,
        decision: HumanDecision,
        comments: str | None = None,
        revision_reason: str | None = None,
        revision_requirements: list[str] | None = None,
    ) -> NewsTaskState:
        state = await self._tasks.get_task(task_id)
        await self._ensure_idle(task_id, wait=True)
        if state.task_status != TaskStatus.HUMAN_REVIEW:
            raise ConflictError("当前任务不在待人工处理状态")
        if not await self.workflow.has_pending_interrupt(task_id):
            raise ConflictError("任务当前不在等待人工输入")

        payload: dict[str, Any] = {"decision": decision.value}
        if comments:
            payload["comments"] = comments
        if decision in _REVISION_DECISIONS:
            payload["revision_reason"] = (revision_reason or "").strip()
            payload["revision_requirements"] = [
                item.strip() for item in (revision_requirements or []) if item.strip()
            ]

        token = await self._acquire(task_id)
        state.task_status = TaskStatus.RUNNING
        state.paused = False
        state.touch()
        await self._tasks.save_state(state)
        self._start_job(
            state,
            token,
            lambda: self.workflow.stream_continue(task_id, payload),
        )
        return state

    async def submit_manual_edit(
        self,
        task_id: str,
        *,
        article: ArticleContent,
        version: int,
    ) -> NewsTaskState:
        state = await self._tasks.get_task(task_id)
        await self._ensure_idle(task_id, wait=True)
        if state.task_status not in {TaskStatus.HUMAN_REVIEW, TaskStatus.PENDING_REVIEW}:
            raise ConflictError("当前任务不在可编辑环节")
        current_version = state.article_version or 0
        if version <= current_version:
            raise ConflictError(f"新版本号必须大于当前版本 {current_version}")

        token = await self._acquire(task_id)
        state.edited_article = article
        state.article_id = state.article_id or generate_id("ART")
        state.article_version = version
        state.fact_check_report = None
        state.special_check_report = None
        state.chief_decision = None
        state.review_comments = None
        state.human_decision = None
        state.revision_request = None
        state.delivery_package = None
        state.task_status = TaskStatus.RUNNING
        state.current_stage = WorkflowStage.FACT_CHECK
        state.paused = False
        state.error = None
        state.touch()
        await self._tasks.save_state(state)

        # Full state keeps the recheck self-contained: after a restart the
        # in-memory checkpoint is gone and aupdate_state starts from this payload.
        values = state.model_dump(mode="json")
        self._start_job(
            state,
            token,
            lambda: self.workflow.stream_recheck(task_id, values),
        )
        return state

    async def recover_stale_tasks(self) -> int:
        """Fail tasks left RUNNING by a previous process; checkpoints are in-memory."""
        recovered = 0
        for state in await self._tasks.list_all():
            if state.task_status != TaskStatus.RUNNING or self.is_running(state.task_id):
                continue
            state.task_status = TaskStatus.FAILED
            state.current_stage = WorkflowStage.ERROR
            state.paused = False
            state.error = ErrorInfo(
                code="WORKER_RESTARTED",
                message="服务重启后执行检查点已丢失，任务已停止",
            )
            state.touch()
            await self._tasks.save_state(state)
            recovered += 1
        return recovered

    async def get_delivery(self, task_id: str) -> DeliveryPackage:
        state = await self._tasks.get_task(task_id)
        if state.delivery_package is None:
            raise ConflictError("交付材料尚未生成")
        return state.delivery_package

    async def confirm_delivery(self, task_id: str, *, confirmed: bool) -> NewsTaskState:
        state = await self._tasks.get_task(task_id)
        if state.task_status != TaskStatus.PENDING_REVIEW:
            raise ConflictError("当前任务不在待复核环节")
        if not confirmed:
            return state
        state.task_status = TaskStatus.DELIVERED
        state.current_stage = WorkflowStage.DELIVERED
        state.touch()
        await self._tasks.save_state(state)
        return state

    async def list_events(self, task_id: str) -> list[ExecutionLogEntry]:
        return await self._tasks.list_events(task_id)

    def _start_job(
        self,
        state: NewsTaskState,
        token: str,
        stream_factory,
    ) -> None:
        job = ExecutionJob(task_id=state.task_id, latest_state=state)
        self._jobs[state.task_id] = job
        job.handle = asyncio.create_task(
            self._run_job(job, token, stream_factory)
        )

    async def _run_job(
        self,
        job: ExecutionJob,
        token: str,
        stream_factory,
    ) -> None:
        latest = job.latest_state
        fingerprint = self._fingerprint(latest)
        try:
            stream: AsyncIterator[dict[str, Any]] = stream_factory()
            first = True
            async for chunk in stream:
                if first:
                    first = False
                    continue
                latest = state_from_values(chunk)
                if job.pause_requested:
                    latest.paused = True
                current = self._fingerprint(latest)
                if current != fingerprint:
                    latest.touch()
                    await self._tasks.save_state(latest)
                    fingerprint = current
                job.latest_state = latest
                if "__interrupt__" in chunk:
                    break
                if job.pause_requested:
                    latest.paused = True
                    latest.touch()
                    await self._tasks.save_state(latest)
                    break
        except Exception as exc:
            logger.exception("workflow execution crashed task_id=%s", job.task_id)
            failed = job.latest_state
            failed.task_status = TaskStatus.FAILED
            failed.current_stage = WorkflowStage.ERROR
            failed.error = ErrorInfo(
                code="RUNTIME_ERROR",
                message=f"{type(exc).__name__}: {exc}",
            )
            failed.paused = False
            failed.touch()
            await self._tasks.save_state(failed)
        finally:
            latest = job.latest_state
            if (
                latest.paused
                and latest.task_status
                not in {TaskStatus.CREATED, TaskStatus.RUNNING}
            ):
                latest.paused = False
                latest.touch()
                await self._tasks.save_state(latest)
            if self._jobs.get(job.task_id) is job:
                self._jobs.pop(job.task_id, None)
            await self._tasks.release_lock(job.task_id, token)

    @staticmethod
    def _fingerprint(state: NewsTaskState) -> tuple[Any, ...]:
        return (
            len(state.execution_logs),
            state.task_status,
            state.current_stage,
            state.paused,
        )

    async def _ensure_idle(self, task_id: str, *, wait: bool = False) -> None:
        job = self._jobs.get(task_id)
        if job is None:
            return
        handle = job.handle
        if handle is not None and not handle.done():
            if not wait:
                raise BusyError("任务正在执行，请稍后重试")
            try:
                await asyncio.wait_for(asyncio.shield(handle), timeout=5)
            except TimeoutError:
                raise BusyError("任务正在执行，请稍后重试") from None
        self._jobs.pop(task_id, None)

    async def _acquire(self, task_id: str) -> str:
        token = generate_id("LOCK")
        acquired = await self._tasks.try_acquire_lock(
            task_id, token, ttl_seconds=self._lock_ttl
        )
        if not acquired:
            raise BusyError("任务正在执行，请稍后重试")
        return token
