from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_task_service
from app.api.response import ok
from app.schemas.api import (
    ApiResponse,
    Page,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskDetail,
    TaskSummary,
)
from app.schemas.enums import TaskStatus
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=ApiResponse[TaskCreateResponse], status_code=201)
async def create_task(
    payload: TaskCreateRequest,
    request: Request,
    service: TaskService = Depends(get_task_service),
) -> ApiResponse[TaskCreateResponse]:
    state = await service.create_task(
        topic=payload.topic,
        description=payload.description,
        requirements=payload.requirements,
    )
    return ok(
        request,
        TaskCreateResponse(
            task_id=state.task_id,
            status=state.task_status,
            created_at=state.created_at,
        ),
    )


@router.get("", response_model=ApiResponse[Page[TaskSummary]])
async def list_tasks(
    request: Request,
    status: TaskStatus | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: TaskService = Depends(get_task_service),
) -> ApiResponse[Page[TaskSummary]]:
    tasks, total = await service.list_tasks(
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ok(
        request,
        Page(
            items=[TaskSummary.from_state(task) for task in tasks],
            page=page,
            page_size=page_size,
            total=total,
        ),
    )


@router.get("/{task_id}", response_model=ApiResponse[TaskDetail])
async def get_task(
    task_id: str,
    request: Request,
    service: TaskService = Depends(get_task_service),
) -> ApiResponse[TaskDetail]:
    state = await service.get_task(task_id)
    return ok(request, TaskDetail.from_state(state))


@router.post("/{task_id}/cancel", response_model=ApiResponse[TaskSummary])
async def cancel_task(
    task_id: str,
    request: Request,
    service: TaskService = Depends(get_task_service),
) -> ApiResponse[TaskSummary]:
    state = await service.cancel_task(task_id)
    return ok(request, TaskSummary.from_state(state))
