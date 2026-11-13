import pytest
from pydantic import ValidationError

from app.core.utils import utc_now
from app.graph.state import NewsTaskState
from app.schemas.domain import (
    FactCheckReport,
    Publication,
    SourceEvidence,
    VerificationClaim,
)
from app.schemas.enums import (
    ClaimVerificationResult,
    FactCheckOverallResult,
    PublicationStatus,
    TaskStatus,
    WorkflowStage,
)


def make_state(**overrides) -> NewsTaskState:
    values = {"task_id": "TASK_TEST", "topic": "人工智能在高校教育中的应用"}
    values.update(overrides)
    return NewsTaskState(**values)


def verified_claim() -> VerificationClaim:
    return VerificationClaim(
        claim="某高校已开展人工智能教学实践",
        result=ClaimVerificationResult.VERIFIED,
        evidence=[
            SourceEvidence(
                source_id="SRC_001",
                url="https://example.com/article",
                supporting_excerpt="该校已启动人工智能课程试点。",
            )
        ],
        reason="存在可靠来源支持",
    )


def passed_report(
    *, article_id: str = "ARTICLE_001", article_version: int = 1
) -> FactCheckReport:
    return FactCheckReport(
        report_id="RPT_001",
        article_id=article_id,
        article_version=article_version,
        overall_result=FactCheckOverallResult.PASSED,
        claims=[verified_claim()],
    )


def test_state_defaults():
    state = make_state()

    assert state.task_status == TaskStatus.CREATED
    assert state.current_stage == WorkflowStage.CREATED
    assert state.retry_count == 0
    assert state.research_sources == []
    assert state.execution_logs == []
    assert state.user_confirmation is False
    assert state.created_at.tzinfo is not None


def test_state_serializes_enums_as_strings():
    payload = make_state().model_dump(mode="json")

    assert payload["task_status"] == "CREATED"
    assert payload["current_stage"] == "created"
    assert payload["requirements"]["target_length"] == 1500


def test_state_rejects_unknown_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        make_state(unexpected="value")


def test_fact_check_report_requires_article_binding():
    with pytest.raises(ValidationError, match="article_id"):
        make_state(fact_check_report=passed_report())


def test_fact_check_report_version_must_match_article_version():
    with pytest.raises(ValidationError, match="article_version"):
        make_state(
            article_id="ARTICLE_001",
            article_version=2,
            fact_check_report=passed_report(article_version=1),
        )


def test_fact_check_report_article_must_match():
    with pytest.raises(ValidationError, match="article_id"):
        make_state(
            article_id="ARTICLE_OTHER",
            article_version=1,
            fact_check_report=passed_report(article_id="ARTICLE_001"),
        )


def test_published_task_requires_user_confirmation():
    publication = Publication(
        article_id="ARTICLE_001",
        article_version=1,
        status=PublicationStatus.PUBLISHED,
        published_at=utc_now(),
    )

    with pytest.raises(ValidationError, match="user_confirmation"):
        make_state(
            task_status=TaskStatus.PUBLISHED,
            publication=publication,
            user_confirmation=False,
        )


def test_published_task_accepts_confirmed_publication():
    publication = Publication(
        article_id="ARTICLE_001",
        article_version=1,
        status=PublicationStatus.PUBLISHED,
        published_at=utc_now(),
    )

    state = make_state(
        task_status=TaskStatus.PUBLISHED,
        publication=publication,
        user_confirmation=True,
    )

    assert state.task_status == TaskStatus.PUBLISHED
    assert state.publication.status == PublicationStatus.PUBLISHED
