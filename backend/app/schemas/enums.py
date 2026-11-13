"""Shared enums for the newsroom domain."""
from enum import StrEnum


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RESEARCHING = "RESEARCHING"
    WRITING = "WRITING"
    EDITING = "EDITING"
    FACT_CHECKING = "FACT_CHECKING"
    REVIEWING = "REVIEWING"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    PENDING_PUBLISH = "PENDING_PUBLISH"
    PUBLISHED = "PUBLISHED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkflowStage(StrEnum):
    CREATED = "created"
    CHIEF_PLANNING = "chief_planning"
    RESEARCH = "research"
    WRITING = "writing"
    EDITING = "editing"
    FACT_CHECK = "fact_check"
    CHIEF_REVIEW = "chief_review"
    REVISION_REQUIRED = "revision_required"
    HUMAN_APPROVAL = "human_approval"
    PENDING_PUBLISH = "pending_publish"
    PUBLISHED = "published"
    ERROR = "error"
    CANCELLED = "cancelled"


class ChiefDecision(StrEnum):
    APPROVE = "APPROVE"
    REQUEST_EDIT = "REQUEST_EDIT"
    REQUEST_RESEARCH = "REQUEST_RESEARCH"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class HumanDecision(StrEnum):
    APPROVE = "APPROVE"
    REQUEST_EDIT = "REQUEST_EDIT"
    REQUEST_RESEARCH = "REQUEST_RESEARCH"
    TERMINATE = "TERMINATE"


class AgentName(StrEnum):
    CHIEF_EDITOR = "chief_editor"
    REPORTER = "reporter"
    EDITOR = "editor"
    FACT_CHECKER = "fact_checker"
    PUBLISHER = "publisher"


class AgentStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ClaimVerificationResult(StrEnum):
    VERIFIED = "VERIFIED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIED = "UNVERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"


class FactCheckOverallResult(StrEnum):
    PASSED = "PASSED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class PublicationStatus(StrEnum):
    PENDING_PUBLISH = "PENDING_PUBLISH"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class RevisionTarget(StrEnum):
    REPORTER = "reporter"
    EDITOR = "editor"
