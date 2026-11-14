from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_demo_service
from app.api.response import ok
from app.schemas.demo import DemoConfirmRequest, DemoReviewRequest, DemoStartRequest
from app.services.demo_service import DemoService

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/meta")
async def demo_meta(
    request: Request,
    service: DemoService = Depends(get_demo_service),
) -> Any:
    return ok(request, service.meta())


@router.post("/tasks", status_code=202)
async def start_demo_task(
    payload: DemoStartRequest,
    request: Request,
    service: DemoService = Depends(get_demo_service),
) -> Any:
    job = service.start(
        topic=payload.topic,
        description=payload.description,
        requirements=payload.requirements,
    )
    return ok(request, {"task_id": job.task_id, "phase": "running"})


@router.get("/tasks/{task_id}")
async def get_demo_task(
    task_id: str,
    request: Request,
    service: DemoService = Depends(get_demo_service),
) -> Any:
    return ok(request, service.snapshot(task_id))


@router.post("/tasks/{task_id}/review")
async def submit_demo_review(
    task_id: str,
    payload: DemoReviewRequest,
    request: Request,
    service: DemoService = Depends(get_demo_service),
) -> Any:
    service.submit_review(
        task_id,
        decision=payload.decision,
        comments=payload.comments,
        revision_reason=payload.revision_reason,
        revision_requirements=[
            item.strip() for item in payload.revision_requirements if item.strip()
        ],
    )
    return ok(request, {"task_id": task_id, "phase": "running"})


@router.post("/tasks/{task_id}/confirm")
async def submit_demo_confirmation(
    task_id: str,
    payload: DemoConfirmRequest,
    request: Request,
    service: DemoService = Depends(get_demo_service),
) -> Any:
    service.submit_confirmation(task_id, confirm=payload.confirm)
    return ok(request, {"task_id": task_id, "phase": "running"})
