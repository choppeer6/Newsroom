from asyncio import Lock
from datetime import datetime, timedelta
from typing import Protocol

from app.core.utils import utc_now
from app.graph.state import NewsTaskState
from app.schemas.domain import ExecutionLogEntry


class TaskStore(Protocol):
    async def add(self, task: NewsTaskState) -> None: ...

    async def get(self, task_id: str) -> NewsTaskState | None: ...

    async def update(self, task: NewsTaskState) -> None: ...

    async def list_all(self) -> list[NewsTaskState]: ...

    async def add_event(self, task_id: str, entry: ExecutionLogEntry) -> None: ...

    async def list_events(self, task_id: str) -> list[ExecutionLogEntry]: ...

    async def try_acquire_lock(
        self, task_id: str, token: str, *, ttl_seconds: int = 60
    ) -> bool: ...

    async def release_lock(self, task_id: str, token: str) -> None: ...


class InMemoryTaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, NewsTaskState] = {}
        self._events: dict[str, list[ExecutionLogEntry]] = {}
        self._locks: dict[str, tuple[str, datetime]] = {}
        self._lock = Lock()

    async def add(self, task: NewsTaskState) -> None:
        async with self._lock:
            if task.task_id in self._tasks:
                raise ValueError(f"task already exists: {task.task_id}")
            self._tasks[task.task_id] = task.model_copy(deep=True)
            self._sync_events_locked(task)

    async def get(self, task_id: str) -> NewsTaskState | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            return task.model_copy(deep=True) if task is not None else None

    async def update(self, task: NewsTaskState) -> None:
        async with self._lock:
            if task.task_id not in self._tasks:
                raise KeyError(task.task_id)
            self._tasks[task.task_id] = task.model_copy(deep=True)
            self._sync_events_locked(task)

    async def list_all(self) -> list[NewsTaskState]:
        async with self._lock:
            return [task.model_copy(deep=True) for task in self._tasks.values()]

    async def add_event(self, task_id: str, entry: ExecutionLogEntry) -> None:
        async with self._lock:
            events = self._events.setdefault(task_id, [])
            if all(item.log_id != entry.log_id for item in events):
                events.append(entry.model_copy(deep=True))

    async def list_events(self, task_id: str) -> list[ExecutionLogEntry]:
        async with self._lock:
            return [
                entry.model_copy(deep=True)
                for entry in self._events.get(task_id, [])
            ]

    async def try_acquire_lock(
        self, task_id: str, token: str, *, ttl_seconds: int = 60
    ) -> bool:
        async with self._lock:
            if task_id not in self._tasks:
                return False
            current = self._locks.get(task_id)
            now = utc_now()
            if current is not None and current[1] > now:
                return False
            self._locks[task_id] = (token, now + timedelta(seconds=ttl_seconds))
            return True

    async def release_lock(self, task_id: str, token: str) -> None:
        async with self._lock:
            current = self._locks.get(task_id)
            if current is not None and current[0] == token:
                self._locks.pop(task_id, None)

    def _sync_events_locked(self, task: NewsTaskState) -> None:
        events = self._events.setdefault(task.task_id, [])
        known = {entry.log_id for entry in events}
        for entry in task.execution_logs:
            if entry.log_id not in known:
                events.append(entry.model_copy(deep=True))
                known.add(entry.log_id)
