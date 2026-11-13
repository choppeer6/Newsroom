from datetime import datetime
from typing import Generic, TypeVar

from pydantic import Field

from app.graph.state import NewsTaskState
from app.schemas.base import StrictModel
from app.schemas.domain import ErrorInfo, FactCheckReport, TaskRequirements
from app.schemas.enums import (
    FactCheckOverallResult,
    PublicationStatus,
    TaskStatus,
    WorkflowStage,
)

T = TypeVar("T")


class ApiResponse(StrictModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T
    request_id: str


class Page(StrictModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int


class HealthData(StrictModel):
    status: str = "ok"
    version: str
    environment: str
    llm_configured: bool
    search_configured: bool


class TaskCreateRequest(StrictModel):
    topic: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    requirements: TaskRequirements = Field(default_factory=TaskRequirements)


class TaskCreateResponse(StrictModel):
    task_id: str
    status: TaskStatus
    created_at: datetime


class FactCheckSummary(StrictModel):
    report_id: str
    article_version: int
    overall_result: FactCheckOverallResult


class TaskSummary(StrictModel):
    task_id: str
    topic: str
    status: TaskStatus
    current_stage: WorkflowStage
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_state(cls, state: NewsTaskState) -> "TaskSummary":
        return cls(
            task_id=state.task_id,
            topic=state.topic,
            status=state.task_status,
            current_stage=state.current_stage,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )


class TaskDetail(TaskSummary):
    description: str
    requirements: TaskRequirements
    retry_count: int
    article_version: int | None
    latest_fact_check: FactCheckSummary | None
    publication_status: PublicationStatus | None
    error: ErrorInfo | None

    @classmethod
    def from_state(cls, state: NewsTaskState) -> "TaskDetail":
        report: FactCheckReport | None = state.fact_check_report
        return cls(
            task_id=state.task_id,
            topic=state.topic,
            status=state.task_status,
            current_stage=state.current_stage,
            created_at=state.created_at,
            updated_at=state.updated_at,
            description=state.description,
            requirements=state.requirements,
            retry_count=state.retry_count,
            article_version=state.article_version,
            latest_fact_check=(
                FactCheckSummary(
                    report_id=report.report_id,
                    article_version=report.article_version,
                    overall_result=report.overall_result,
                )
                if report is not None
                else None
            ),
            publication_status=(
                state.publication.status if state.publication is not None else None
            ),
            error=state.error,
        )
