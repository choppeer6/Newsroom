from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_execution_service, get_task_service
from app.api.response import ok
from app.schemas.api import (
    ApiResponse,
    DeliveryConfirmRequest,
    HumanReviewRequest,
    Page,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskDetail,
    TaskSummary,
)
from app.schemas.domain import DeliveryPackage, ExecutionLogEntry
from app.schemas.enums import TaskStatus
from app.services.execution_service import ExecutionService
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


@router.post("/{task_id}/execute", response_model=ApiResponse[TaskDetail])
async def execute_task(
    task_id: str,
    request: Request,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[TaskDetail]:
    outcome = await service.execute(task_id)
    return ok(request, TaskDetail.from_state(outcome.state))


@router.post("/{task_id}/pause", response_model=ApiResponse[TaskDetail])
async def pause_task(
    task_id: str,
    request: Request,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[TaskDetail]:
    state = await service.pause(task_id)
    return ok(request, TaskDetail.from_state(state))


@router.post("/{task_id}/resume", response_model=ApiResponse[TaskDetail])
async def resume_task(
    task_id: str,
    request: Request,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[TaskDetail]:
    outcome = await service.resume(task_id)
    return ok(request, TaskDetail.from_state(outcome.state))


@router.post("/{task_id}/human-review", response_model=ApiResponse[TaskDetail])
async def submit_human_review(
    task_id: str,
    payload: HumanReviewRequest,
    request: Request,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[TaskDetail]:
    outcome = await service.submit_human_review(
        task_id,
        decision=payload.decision,
        comments=payload.comments,
        revision_reason=payload.revision_reason,
        revision_requirements=payload.revision_requirements,
    )
    return ok(request, TaskDetail.from_state(outcome.state))


@router.get("/{task_id}/delivery", response_model=ApiResponse[DeliveryPackage])
async def get_delivery(
    task_id: str,
    request: Request,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[DeliveryPackage]:
    package = await service.get_delivery(task_id)
    return ok(request, package)


@router.post("/{task_id}/delivery/confirm", response_model=ApiResponse[TaskDetail])
async def confirm_delivery(
    task_id: str,
    payload: DeliveryConfirmRequest,
    request: Request,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[TaskDetail]:
    state = await service.confirm_delivery(task_id, confirmed=payload.confirmed)
    return ok(request, TaskDetail.from_state(state))


@router.get(
    "/{task_id}/events", response_model=ApiResponse[list[ExecutionLogEntry]]
)
async def list_task_events(
    task_id: str,
    request: Request,
    service: ExecutionService = Depends(get_execution_service),
) -> ApiResponse[list[ExecutionLogEntry]]:
    events = await service.list_events(task_id)
    return ok(request, events)
