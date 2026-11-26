from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.utils import utc_now
from app.graph.state import NewsTaskState
from app.models.execution_event import ExecutionEventRecord
from app.models.task import TaskRecord
from app.schemas.domain import ExecutionLogEntry


class SqlTaskStore:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self._session_factory = session_factory

    async def add(self, task: NewsTaskState) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                session.add(TaskRecord.from_state(task))
                await self._sync_events(session, task)

    async def get(self, task_id: str) -> NewsTaskState | None:
        async with self._session_factory() as session:
            record = await session.get(TaskRecord, task_id)
            return record.to_state() if record is not None else None

    async def update(self, task: NewsTaskState) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                record = await session.get(TaskRecord, task.task_id)
                if record is None:
                    raise KeyError(task.task_id)
                record.apply_state(task)
                await self._sync_events(session, task)

    async def list_all(self) -> list[NewsTaskState]:
        async with self._session_factory() as session:
            records = (
                await session.scalars(select(TaskRecord))
            ).all()
            return [record.to_state() for record in records]

    async def add_event(self, task_id: str, entry: ExecutionLogEntry) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                seq = await self._next_seq(session, task_id)
                session.add(ExecutionEventRecord.from_log(task_id, seq, entry))

    async def list_events(self, task_id: str) -> list[ExecutionLogEntry]:
        async with self._session_factory() as session:
            records = (
                await session.scalars(
                    select(ExecutionEventRecord)
                    .where(ExecutionEventRecord.task_id == task_id)
                    .order_by(ExecutionEventRecord.seq)
                )
            ).all()
            return [record.to_log() for record in records]

    async def try_acquire_lock(
        self, task_id: str, token: str, *, ttl_seconds: int = 60
    ) -> bool:
        now = utc_now()
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    update(TaskRecord)
                    .where(
                        TaskRecord.task_id == task_id,
                        or_(
                            TaskRecord.execution_lock.is_(None),
                            TaskRecord.lock_expires_at < now,
                        ),
                    )
                    .values(
                        execution_lock=token,
                        lock_expires_at=now + timedelta(seconds=ttl_seconds),
                    )
                )
                return result.rowcount == 1

    async def release_lock(self, task_id: str, token: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(TaskRecord)
                    .where(
                        TaskRecord.task_id == task_id,
                        TaskRecord.execution_lock == token,
                    )
                    .values(execution_lock=None, lock_expires_at=None)
                )

    async def _sync_events(
        self, session: AsyncSession, task: NewsTaskState
    ) -> None:
        if not task.execution_logs:
            return
        existing = set(
            (
                await session.scalars(
                    select(ExecutionEventRecord.event_id).where(
                        ExecutionEventRecord.task_id == task.task_id
                    )
                )
            ).all()
        )
        seq = await self._next_seq(session, task.task_id) - 1
        for entry in task.execution_logs:
            if entry.log_id in existing:
                continue
            seq += 1
            session.add(
                ExecutionEventRecord.from_log(task.task_id, seq, entry)
            )
            existing.add(entry.log_id)

    async def _next_seq(self, session: AsyncSession, task_id: str) -> int:
        current = await session.scalar(
            select(func.max(ExecutionEventRecord.seq)).where(
                ExecutionEventRecord.task_id == task_id
            )
        )
        return (current or 0) + 1
