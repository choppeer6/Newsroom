from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from app.core.utils import utc_now
from app.schemas.base import StrictModel
from app.schemas.enums import (
    AgentName,
    AgentStatus,
    ChiefDecision,
    ClaimVerificationResult,
    FactCheckOverallResult,
    PublicationStatus,
    RevisionTarget,
)

URL_PATTERN = r"^https?://\S+$"


class TaskRequirements(StrictModel):
    style: str = Field(default="客观新闻报道", min_length=1, max_length=100)
    target_length: int = Field(default=1500, ge=200, le=5000)
    focus: list[str] = Field(default_factory=list)


class EditorialPlan(StrictModel):
    topic_analysis: str = Field(min_length=1)
    reporting_angles: list[str] = Field(min_length=1)
    research_tasks: list[str] = Field(min_length=1)
    article_outline: list[str] = Field(min_length=1)
    verification_points: list[str] = Field(min_length=1)


class ResearchSource(StrictModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(pattern=URL_PATTERN)
    publisher: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)


class ArticleContent(StrictModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class EditingReport(StrictModel):
    structure_changes: str = Field(min_length=1)
    language_changes: str = Field(min_length=1)
    content_changes: str = Field(min_length=1)


class SourceEvidence(StrictModel):
    source_id: str = Field(min_length=1)
    url: str = Field(pattern=URL_PATTERN)
    supporting_excerpt: str = Field(min_length=1)


class VerificationClaim(StrictModel):
    claim: str = Field(min_length=1)
    result: ClaimVerificationResult
    evidence: list[SourceEvidence] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _evidence_required_when_judged(self) -> "VerificationClaim":
        evidence_results = {
            ClaimVerificationResult.VERIFIED,
            ClaimVerificationResult.CONTRADICTED,
            ClaimVerificationResult.PARTIALLY_VERIFIED,
        }
        if self.result in evidence_results and not self.evidence:
            raise ValueError(f"evidence is required when claim result is {self.result}")
        return self


class FactCheckFinding(StrictModel):
    overall_result: FactCheckOverallResult
    claims: list[VerificationClaim] = Field(min_length=1)
    issues: list[str] = Field(default_factory=list)
    recommendation: ChiefDecision | None = None

    @model_validator(mode="after")
    def _result_matches_claims(self) -> "FactCheckFinding":
        if self.overall_result == FactCheckOverallResult.PASSED:
            if any(claim.result != ClaimVerificationResult.VERIFIED for claim in self.claims):
                raise ValueError("PASSED requires every claim to be VERIFIED")
        if self.overall_result == FactCheckOverallResult.PARTIAL:
            if all(claim.result == ClaimVerificationResult.VERIFIED for claim in self.claims):
                raise ValueError("PARTIAL requires at least one non-VERIFIED claim")
        if self.overall_result == FactCheckOverallResult.FAILED:
            problematic = {
                ClaimVerificationResult.CONTRADICTED,
                ClaimVerificationResult.UNVERIFIED,
            }
            if not any(claim.result in problematic for claim in self.claims):
                raise ValueError("FAILED requires at least one CONTRADICTED or UNVERIFIED claim")
        return self


class FactCheckReport(FactCheckFinding):
    report_id: str = Field(min_length=1)
    article_id: str = Field(min_length=1)
    article_version: int = Field(ge=1)
    created_at: datetime = Field(default_factory=utc_now)


class RevisionRequest(StrictModel):
    target: RevisionTarget
    reason: str = Field(min_length=1)
    requirements: list[str] = Field(min_length=1)
    related_claims: list[str] = Field(default_factory=list)


class Publication(StrictModel):
    publication_id: str | None = None
    article_id: str = Field(min_length=1)
    article_version: int = Field(ge=1)
    status: PublicationStatus = PublicationStatus.PENDING_PUBLISH
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    published_at: datetime | None = None
    external_url: str | None = Field(default=None, pattern=URL_PATTERN)
    message: str | None = None

    @model_validator(mode="after")
    def _status_consistency(self) -> "Publication":
        if self.status == PublicationStatus.PUBLISHED and self.published_at is None:
            raise ValueError("published_at is required when status is PUBLISHED")
        if self.status == PublicationStatus.FAILED and not self.message:
            raise ValueError("message is required when status is FAILED")
        return self


class ErrorInfo(StrictModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False
    details: dict[str, Any] | None = None


class ExecutionLogEntry(StrictModel):
    log_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    agent_name: AgentName
    status: AgentStatus
    input_summary: str | None = None
    output_summary: str | None = None
    error_message: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
