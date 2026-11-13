from datetime import datetime

from pydantic import Field, model_validator

from app.core.utils import utc_now
from app.schemas.base import StrictModel
from app.schemas.domain import (
    ArticleContent,
    EditorialPlan,
    EditingReport,
    ErrorInfo,
    ExecutionLogEntry,
    FactCheckReport,
    Publication,
    ResearchSource,
    RevisionRequest,
    TaskRequirements,
)
from app.schemas.enums import (
    ChiefDecision,
    HumanDecision,
    PublicationStatus,
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
    retry_count: int = Field(default=0, ge=0)

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

    chief_decision: ChiefDecision | None = None
    review_comments: str | None = None
    revision_request: RevisionRequest | None = None

    human_decision: HumanDecision | None = None
    user_confirmation: bool = False
    publication: Publication | None = None

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
            raise ValueError("fact_check_report.article_version does not match article_version")
        return self

    @model_validator(mode="after")
    def _publication_requires_confirmation(self) -> "NewsTaskState":
        publication = self.publication
        if publication is not None and publication.status == PublicationStatus.PUBLISHED:
            if not self.user_confirmation:
                raise ValueError("user_confirmation is required before a task is PUBLISHED")
            if self.task_status != TaskStatus.PUBLISHED:
                raise ValueError("task_status must be PUBLISHED when publication is PUBLISHED")
        if self.task_status == TaskStatus.PUBLISHED:
            if publication is None or publication.status != PublicationStatus.PUBLISHED:
                raise ValueError("PUBLISHED task requires a PUBLISHED publication record")
            if not self.user_confirmation:
                raise ValueError("PUBLISHED task requires user_confirmation")
        return self
