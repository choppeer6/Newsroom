from asyncio import Lock

from app.graph.state import NewsTaskState


class InMemoryTaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, NewsTaskState] = {}
        self._lock = Lock()

    async def add(self, task: NewsTaskState) -> None:
        async with self._lock:
            if task.task_id in self._tasks:
                raise ValueError(f"task already exists: {task.task_id}")
            self._tasks[task.task_id] = task.model_copy(deep=True)

    async def get(self, task_id: str) -> NewsTaskState | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            return task.model_copy(deep=True) if task is not None else None

    async def update(self, task: NewsTaskState) -> None:
        async with self._lock:
            if task.task_id not in self._tasks:
                raise KeyError(task.task_id)
            self._tasks[task.task_id] = task.model_copy(deep=True)

    async def list_all(self) -> list[NewsTaskState]:
        async with self._lock:
            return [task.model_copy(deep=True) for task in self._tasks.values()]
