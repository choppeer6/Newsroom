"""Shared enums for the newsroom domain."""
from enum import StrEnum


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    PENDING_REVIEW = "PENDING_REVIEW"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    TERMINATED = "TERMINATED"


class WorkflowStage(StrEnum):
    CREATED = "created"
    CHIEF_PLANNING = "chief_planning"
    RESEARCH = "research"
    EDITING = "editing"
    FACT_CHECK = "fact_check"
    SPECIAL_CHECK = "special_check"
    CHIEF_REVIEW = "chief_review"
    REVISION_REQUIRED = "revision_required"
    HUMAN_REVIEW = "human_review"
    PREPARE_DELIVERY = "prepare_delivery"
    PENDING_REVIEW = "pending_review"
    DELIVERED = "delivered"
    ERROR = "error"
    TERMINATED = "terminated"


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
    SPECIAL_CHECKER = "special_checker"
    DELIVERY_PREPARER = "delivery_preparer"
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


class SpecialCheckResult(StrEnum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


class SpecialCheckSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class PublicationStatus(StrEnum):
    PENDING_PUBLISH = "PENDING_PUBLISH"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class RevisionTarget(StrEnum):
    REPORTER = "reporter"
    EDITOR = "editor"
