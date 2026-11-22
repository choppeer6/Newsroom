from typing import Literal, NamedTuple

from pydantic import Field, model_validator

from app.schemas.base import StrictModel
from app.schemas.domain import (
    ArticleContent,
    DeliveryPackage,
    EditorialPlan,
    EditingReport,
    ErrorInfo,
    FactCheckFinding,
    FactCheckReport,
    Publication,
    ResearchSource,
    RevisionRequest,
    SpecialCheckFinding,
    SpecialCheckReport,
    TaskRequirements,
)
from app.schemas.enums import (
    AgentStatus,
    ChiefDecision,
    FactCheckOverallResult,
    RevisionTarget,
    SpecialCheckResult,
)


class AgentInput(StrictModel):
    task_id: str = Field(min_length=1)


class AgentOutput(StrictModel):
    status: AgentStatus = AgentStatus.COMPLETED
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def _error_matches_status(self) -> "AgentOutput":
        if self.status == AgentStatus.FAILED and self.error is None:
            raise ValueError("error is required when status is FAILED")
        if self.status == AgentStatus.COMPLETED and self.error is not None:
            raise ValueError("error must be None when status is COMPLETED")
        return self


class ChiefPlanningInput(AgentInput):
    topic: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    requirements: TaskRequirements = Field(default_factory=TaskRequirements)


class ChiefPlanningOutput(AgentOutput):
    editorial_plan: EditorialPlan | None = None
    next_agent: Literal["reporter"] = "reporter"

    @model_validator(mode="after")
    def _payload_when_completed(self) -> "ChiefPlanningOutput":
        if self.status == AgentStatus.COMPLETED and self.editorial_plan is None:
            raise ValueError("editorial_plan is required when status is COMPLETED")
        return self


class ReporterInput(AgentInput):
    editorial_plan: EditorialPlan
    requirements: TaskRequirements = Field(default_factory=TaskRequirements)
    revision_request: RevisionRequest | None = None
    existing_sources: list[ResearchSource] = Field(default_factory=list)
    previous_draft: ArticleContent | None = None


class ReporterOutput(AgentOutput):
    draft: ArticleContent | None = None
    sources: list[ResearchSource] = Field(default_factory=list)
    research_summary: str | None = None
    unverified_claims: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _payload_when_completed(self) -> "ReporterOutput":
        if self.status == AgentStatus.COMPLETED:
            if self.draft is None:
                raise ValueError("draft is required when status is COMPLETED")
            if not self.sources:
                raise ValueError("sources must not be empty when status is COMPLETED")
            if not self.research_summary:
                raise ValueError("research_summary is required when status is COMPLETED")
        return self


class EditorInput(AgentInput):
    draft: ArticleContent
    requirements: TaskRequirements = Field(default_factory=TaskRequirements)
    revision_request: RevisionRequest | None = None
    review_comments: str | None = None
    fact_check_report: FactCheckReport | None = None
    current_version: int = Field(default=1, ge=1)


class EditorOutput(AgentOutput):
    edited_article: ArticleContent | None = None
    editing_report: EditingReport | None = None
    version: int | None = Field(default=None, ge=2)

    @model_validator(mode="after")
    def _payload_when_completed(self) -> "EditorOutput":
        if self.status == AgentStatus.COMPLETED:
            if self.edited_article is None:
                raise ValueError("edited_article is required when status is COMPLETED")
            if self.editing_report is None:
                raise ValueError("editing_report is required when status is COMPLETED")
            if self.version is None:
                raise ValueError("version is required when status is COMPLETED")
        return self


class FactCheckerInput(AgentInput):
    article_id: str = Field(min_length=1)
    article: ArticleContent
    article_version: int = Field(ge=1)
    sources: list[ResearchSource] = Field(default_factory=list)


class FactCheckerOutput(AgentOutput):
    verification_report: FactCheckFinding | None = None
    article_id: str | None = None
    article_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _payload_when_completed(self) -> "FactCheckerOutput":
        if self.status == AgentStatus.COMPLETED:
            if self.verification_report is None:
                raise ValueError("verification_report is required when status is COMPLETED")
            if self.article_id is None:
                raise ValueError("article_id is required when status is COMPLETED")
            if self.article_version is None:
                raise ValueError("article_version is required when status is COMPLETED")
        return self


class SpecialCheckInput(AgentInput):
    article_id: str = Field(min_length=1)
    article: ArticleContent
    article_version: int = Field(ge=1)
    fact_check_report: FactCheckReport
    sources: list[ResearchSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def _report_binding(self) -> "SpecialCheckInput":
        if self.fact_check_report.article_id != self.article_id:
            raise ValueError("fact_check_report.article_id does not match article_id")
        if self.fact_check_report.article_version != self.article_version:
            raise ValueError(
                "fact_check_report.article_version does not match article_version"
            )
        return self


class SpecialCheckOutput(AgentOutput):
    finding: SpecialCheckFinding | None = None
    article_id: str | None = None
    article_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _payload_when_completed(self) -> "SpecialCheckOutput":
        if self.status == AgentStatus.COMPLETED:
            if self.finding is None:
                raise ValueError("finding is required when status is COMPLETED")
            if self.article_id is None:
                raise ValueError("article_id is required when status is COMPLETED")
            if self.article_version is None:
                raise ValueError("article_version is required when status is COMPLETED")
        return self


class ChiefReviewInput(AgentInput):
    topic: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    requirements: TaskRequirements = Field(default_factory=TaskRequirements)
    editorial_plan: EditorialPlan
    sources: list[ResearchSource] = Field(default_factory=list)
    edited_article: ArticleContent
    article_id: str = Field(min_length=1)
    article_version: int = Field(ge=1)
    fact_check_report: FactCheckReport
    special_check_report: SpecialCheckReport
    revision_round: int = Field(default=0, ge=0)
    max_revision_rounds: int = Field(default=2, ge=0)

    @model_validator(mode="after")
    def _reports_match_article(self) -> "ChiefReviewInput":
        for name, report in (
            ("fact_check_report", self.fact_check_report),
            ("special_check_report", self.special_check_report),
        ):
            if report.article_id != self.article_id:
                raise ValueError(f"{name}.article_id does not match article_id")
            if report.article_version != self.article_version:
                raise ValueError(
                    f"{name}.article_version does not match article_version"
                )
        return self


class ChiefReviewOutput(AgentOutput):
    chief_decision: ChiefDecision | None = None
    review_comments: str | None = None
    revision_request: RevisionRequest | None = None

    @model_validator(mode="after")
    def _decision_contract(self) -> "ChiefReviewOutput":
        if self.status != AgentStatus.COMPLETED:
            return self
        if self.chief_decision is None:
            raise ValueError("chief_decision is required when status is COMPLETED")
        if not self.review_comments:
            raise ValueError("review_comments is required when status is COMPLETED")

        if self.chief_decision == ChiefDecision.APPROVE:
            if self.revision_request is not None:
                raise ValueError("APPROVE must not include revision_request")
        elif self.chief_decision == ChiefDecision.REQUEST_EDIT:
            if self.revision_request is None:
                raise ValueError("REQUEST_EDIT requires revision_request")
            if self.revision_request.target != RevisionTarget.EDITOR:
                raise ValueError("REQUEST_EDIT requires revision_request.target=editor")
        elif self.chief_decision == ChiefDecision.REQUEST_RESEARCH:
            if self.revision_request is None:
                raise ValueError("REQUEST_RESEARCH requires revision_request")
            if self.revision_request.target != RevisionTarget.REPORTER:
                raise ValueError("REQUEST_RESEARCH requires revision_request.target=reporter")
        return self


class DeliveryPreparationInput(AgentInput):
    article_id: str = Field(min_length=1)
    article: ArticleContent
    article_version: int = Field(ge=1)
    fact_check_report: FactCheckReport
    special_check_report: SpecialCheckReport
    sources: list[ResearchSource] = Field(default_factory=list)

    @model_validator(mode="after")
    def _delivery_preconditions(self) -> "DeliveryPreparationInput":
        if self.fact_check_report.overall_result == FactCheckOverallResult.FAILED:
            raise ValueError("delivery rejects articles with FAILED fact check")
        if self.special_check_report.result == SpecialCheckResult.BLOCKED:
            raise ValueError("delivery rejects articles with BLOCKED special check")
        for name, report in (
            ("fact_check_report", self.fact_check_report),
            ("special_check_report", self.special_check_report),
        ):
            if report.article_id != self.article_id:
                raise ValueError(f"{name}.article_id does not match article_id")
            if report.article_version != self.article_version:
                raise ValueError(
                    f"{name}.article_version does not match article_version"
                )
        return self


class DeliveryPreparationOutput(AgentOutput):
    package: DeliveryPackage | None = None

    @model_validator(mode="after")
    def _payload_when_completed(self) -> "DeliveryPreparationOutput":
        if self.status == AgentStatus.COMPLETED and self.package is None:
            raise ValueError("package is required when status is COMPLETED")
        return self


class PublisherInput(AgentInput):
    article_id: str = Field(min_length=1)
    article: ArticleContent
    article_version: int = Field(ge=1)
    chief_decision: ChiefDecision
    fact_check_status: FactCheckOverallResult
    user_confirmation: bool = False

    @model_validator(mode="after")
    def _publish_preconditions(self) -> "PublisherInput":
        if self.chief_decision != ChiefDecision.APPROVE:
            raise ValueError("publisher requires chief_decision=APPROVE")
        if self.fact_check_status == FactCheckOverallResult.FAILED:
            raise ValueError("publisher rejects articles with FAILED fact check")
        return self


class PublisherOutput(AgentOutput):
    publication: Publication | None = None

    @model_validator(mode="after")
    def _payload_when_completed(self) -> "PublisherOutput":
        if self.status == AgentStatus.COMPLETED and self.publication is None:
            raise ValueError("publication is required when status is COMPLETED")
        return self


class AgentContract(NamedTuple):
    input: type[AgentInput]
    output: type[AgentOutput]


AGENT_CONTRACTS: dict[str, AgentContract] = {
    "chief_planning": AgentContract(ChiefPlanningInput, ChiefPlanningOutput),
    "reporter": AgentContract(ReporterInput, ReporterOutput),
    "editor": AgentContract(EditorInput, EditorOutput),
    "fact_checker": AgentContract(FactCheckerInput, FactCheckerOutput),
    "special_check": AgentContract(SpecialCheckInput, SpecialCheckOutput),
    "chief_review": AgentContract(ChiefReviewInput, ChiefReviewOutput),
    "prepare_delivery": AgentContract(
        DeliveryPreparationInput, DeliveryPreparationOutput
    ),
}
