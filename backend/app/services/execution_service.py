"""Synchronous task execution service for the formal task API."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.errors import BusyError, ConflictError
from app.core.utils import generate_id
from app.graph.state import NewsTaskState
from app.graph.workflow import NewsroomWorkflow, WorkflowResult
from app.schemas.domain import DeliveryPackage, ErrorInfo, ExecutionLogEntry
from app.schemas.enums import HumanDecision, TaskStatus, WorkflowStage
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)

_REVISION_DECISIONS = {HumanDecision.REQUEST_EDIT, HumanDecision.REQUEST_RESEARCH}


@dataclass(frozen=True)
class ExecutionOutcome:
    state: NewsTaskState
    interrupt: dict[str, Any] | None = None


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

    @property
    def workflow(self) -> NewsroomWorkflow:
        if self._workflow is None:
            self._workflow = NewsroomWorkflow()
        return self._workflow

    async def execute(self, task_id: str) -> ExecutionOutcome:
        state = await self._tasks.get_task(task_id)
        if state.paused:
            raise ConflictError("任务已暂停，请先恢复")
        if state.task_status == TaskStatus.RUNNING:
            raise ConflictError("任务正在执行")
        if state.task_status != TaskStatus.CREATED:
            raise ConflictError(f"任务状态 {state.task_status} 不允许执行")
        return await self._run(state, lambda: self.workflow.run(state))

    async def pause(self, task_id: str) -> NewsTaskState:
        state = await self._tasks.get_task(task_id)
        if state.task_status not in {TaskStatus.CREATED, TaskStatus.RUNNING}:
            raise ConflictError(f"任务状态 {state.task_status} 不允许暂停")
        if state.paused:
            return state
        token = await self._acquire(task_id)
        try:
            state.paused = True
            state.touch()
            await self._tasks.save_state(state)
        finally:
            await self._tasks.release_lock(task_id, token)
        return state

    async def resume(self, task_id: str) -> ExecutionOutcome:
        state = await self._tasks.get_task(task_id)
        if not state.paused:
            raise ConflictError("任务未处于暂停状态")
        if state.task_status != TaskStatus.CREATED:
            raise ConflictError(f"任务状态 {state.task_status} 不允许恢复")
        state.paused = False
        await self._tasks.save_state(state)
        return await self.execute(task_id)

    async def submit_human_review(
        self,
        task_id: str,
        *,
        decision: HumanDecision,
        comments: str | None = None,
        revision_reason: str | None = None,
        revision_requirements: list[str] | None = None,
    ) -> ExecutionOutcome:
        state = await self._tasks.get_task(task_id)
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
        return await self._run(
            state, lambda: self.workflow.resume(task_id, payload)
        )

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

    async def _run(
        self,
        state: NewsTaskState,
        runner: Callable[[], Awaitable[WorkflowResult]],
    ) -> ExecutionOutcome:
        token = await self._acquire(state.task_id)
        try:
            try:
                result = await runner()
            except Exception as exc:
                logger.exception("workflow execution crashed task_id=%s", state.task_id)
                state.task_status = TaskStatus.FAILED
                state.current_stage = WorkflowStage.ERROR
                state.error = ErrorInfo(
                    code="RUNTIME_ERROR",
                    message=f"{type(exc).__name__}: {exc}",
                )
                state.touch()
                await self._tasks.save_state(state)
                return ExecutionOutcome(state=state)
            await self._tasks.save_state(result.state)
            return ExecutionOutcome(
                state=result.state,
                interrupt=result.interrupt,
            )
        finally:
            await self._tasks.release_lock(state.task_id, token)

    async def _acquire(self, task_id: str) -> str:
        token = generate_id("LOCK")
        acquired = await self._tasks.try_acquire_lock(
            task_id, token, ttl_seconds=self._lock_ttl
        )
        if not acquired:
            raise BusyError("任务正在执行，请稍后重试")
        return token
