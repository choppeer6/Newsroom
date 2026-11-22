from datetime import datetime
from typing import Generic, TypeVar

from pydantic import Field

from app.graph.state import NewsTaskState
from app.schemas.base import StrictModel
from app.schemas.domain import (
    DeliveryPackage,
    ErrorInfo,
    FactCheckReport,
    SpecialCheckReport,
    TaskRequirements,
)
from app.schemas.enums import (
    FactCheckOverallResult,
    SpecialCheckResult,
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


class SpecialCheckSummary(StrictModel):
    report_id: str
    article_version: int
    result: SpecialCheckResult


class DeliverySummary(StrictModel):
    package_id: str
    article_version: int
    prepared_at: datetime


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
    paused: bool
    revision_round: int
    article_version: int | None
    latest_fact_check: FactCheckSummary | None
    latest_special_check: SpecialCheckSummary | None
    delivery: DeliverySummary | None
    error: ErrorInfo | None

    @classmethod
    def from_state(cls, state: NewsTaskState) -> "TaskDetail":
        report: FactCheckReport | None = state.fact_check_report
        special: SpecialCheckReport | None = state.special_check_report
        package: DeliveryPackage | None = state.delivery_package
        return cls(
            task_id=state.task_id,
            topic=state.topic,
            status=state.task_status,
            current_stage=state.current_stage,
            created_at=state.created_at,
            updated_at=state.updated_at,
            description=state.description,
            requirements=state.requirements,
            paused=state.paused,
            revision_round=state.revision_round,
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
            latest_special_check=(
                SpecialCheckSummary(
                    report_id=special.report_id,
                    article_version=special.article_version,
                    result=special.result,
                )
                if special is not None
                else None
            ),
            delivery=(
                DeliverySummary(
                    package_id=package.package_id,
                    article_version=package.article_version,
                    prepared_at=package.prepared_at,
                )
                if package is not None
                else None
            ),
            error=state.error,
        )
