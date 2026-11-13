from app.core.errors import ConflictError, NotFoundError
from app.core.utils import generate_id
from app.graph.state import NewsTaskState
from app.schemas.domain import TaskRequirements
from app.schemas.enums import TaskStatus, WorkflowStage
from app.services.task_store import InMemoryTaskStore


class TaskService:
    def __init__(self, store: InMemoryTaskStore) -> None:
        self._store = store

    async def create_task(
        self,
        *,
        topic: str,
        description: str,
        requirements: TaskRequirements,
    ) -> NewsTaskState:
        state = NewsTaskState(
            task_id=generate_id("TASK"),
            topic=topic,
            description=description,
            requirements=requirements,
        )
        await self._store.add(state)
        return state

    async def get_task(self, task_id: str) -> NewsTaskState:
        state = await self._store.get(task_id)
        if state is None:
            raise NotFoundError(f"任务不存在: {task_id}")
        return state

    async def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[NewsTaskState], int]:
        tasks = await self._store.list_all()
        if status is not None:
            tasks = [task for task in tasks if task.task_status == status]
        if keyword:
            needle = keyword.strip().lower()
            tasks = [
                task
                for task in tasks
                if needle in task.topic.lower() or needle in task.description.lower()
            ]
        tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
        total = len(tasks)
        start = (page - 1) * page_size
        return tasks[start : start + page_size], total

    async def cancel_task(self, task_id: str) -> NewsTaskState:
        state = await self.get_task(task_id)
        if state.task_status in {TaskStatus.PUBLISHED, TaskStatus.CANCELLED}:
            raise ConflictError(f"任务状态 {state.task_status} 不允许取消")
        state.task_status = TaskStatus.CANCELLED
        state.current_stage = WorkflowStage.CANCELLED
        state.touch()
        await self._store.update(state)
        return state
