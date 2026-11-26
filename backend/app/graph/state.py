from datetime import datetime

from pydantic import Field, model_validator

from app.core.utils import utc_now
from app.schemas.base import StrictModel
from app.schemas.domain import (
    ArticleContent,
    DeliveryPackage,
    EditorialPlan,
    EditingReport,
    ErrorInfo,
    ExecutionLogEntry,
    FactCheckReport,
    ResearchSource,
    RevisionRequest,
    SpecialCheckReport,
    TaskRequirements,
)
from app.schemas.enums import (
    ChiefDecision,
    HumanDecision,
    TaskStatus,
    WorkflowStage,
)


class NewsTaskState(StrictModel):
    task_id: str = Field(min_length=1)
    topic: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    requirements: TaskRequirements = Field(default_factory=TaskRequirements)

    task_status: TaskStatus = TaskStatus.CREATED
    current_stage: WorkflowStage = WorkflowStage.CREATED
    paused: bool = False
    revision_round: int = Field(default=0, ge=0)
    interface_retry_counts: dict[str, int] = Field(default_factory=dict)

    editorial_plan: EditorialPlan | None = None

    research_sources: list[ResearchSource] = Field(default_factory=list)
    research_summary: str | None = None
    unverified_claims: list[str] = Field(default_factory=list)
    draft_article: ArticleContent | None = None

    edited_article: ArticleContent | None = None
    editing_report: EditingReport | None = None
    article_id: str | None = None
    article_version: int | None = Field(default=None, ge=1)

    fact_check_report: FactCheckReport | None = None
    special_check_report: SpecialCheckReport | None = None

    chief_decision: ChiefDecision | None = None
    review_comments: str | None = None
    revision_request: RevisionRequest | None = None

    human_decision: HumanDecision | None = None
    delivery_package: DeliveryPackage | None = None

    execution_logs: list[ExecutionLogEntry] = Field(default_factory=list)
    error: ErrorInfo | None = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()

    @model_validator(mode="after")
    def _fact_check_binding(self) -> "NewsTaskState":
        report = self.fact_check_report
        if report is None:
            return self
        if self.article_id is None or self.article_version is None:
            raise ValueError("fact_check_report requires article_id and article_version")
        if report.article_id != self.article_id:
            raise ValueError("fact_check_report.article_id does not match article_id")
        if report.article_version != self.article_version:
            raise ValueError(
                "fact_check_report.article_version does not match article_version"
            )
        return self

    @model_validator(mode="after")
    def _special_check_binding(self) -> "NewsTaskState":
        report = self.special_check_report
        if report is None:
            return self
        if self.article_id is None or self.article_version is None:
            raise ValueError(
                "special_check_report requires article_id and article_version"
            )
        if report.task_id != self.task_id:
            raise ValueError("special_check_report.task_id does not match task_id")
        if report.article_id != self.article_id:
            raise ValueError(
                "special_check_report.article_id does not match article_id"
            )
        if report.article_version != self.article_version:
            raise ValueError(
                "special_check_report.article_version does not match article_version"
            )
        return self

    @model_validator(mode="after")
    def _delivery_binding(self) -> "NewsTaskState":
        package = self.delivery_package
        if package is None:
            if self.task_status in {
                TaskStatus.PENDING_REVIEW,
                TaskStatus.DELIVERED,
            }:
                raise ValueError(
                    "delivery_package is required for PENDING_REVIEW or DELIVERED"
                )
            return self

        if self.article_id is None or self.article_version is None:
            raise ValueError("delivery_package requires article_id and article_version")
        if package.task_id != self.task_id:
            raise ValueError("delivery_package.task_id does not match task_id")
        if package.article_id != self.article_id:
            raise ValueError("delivery_package.article_id does not match article_id")
        if package.article_version != self.article_version:
            raise ValueError(
                "delivery_package.article_version does not match article_version"
            )
        if (
            self.fact_check_report is None
            or package.fact_check_report_id != self.fact_check_report.report_id
        ):
            raise ValueError(
                "delivery_package.fact_check_report_id does not match current report"
            )
        if (
            self.special_check_report is None
            or package.special_check_report_id != self.special_check_report.report_id
        ):
            raise ValueError(
                "delivery_package.special_check_report_id does not match current report"
            )
        return self
