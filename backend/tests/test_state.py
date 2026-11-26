import pytest
from pydantic import ValidationError

from app.graph.state import NewsTaskState
from app.schemas.domain import (
    DeliveryPackage,
    FactCheckReport,
    SourceEvidence,
    SpecialCheckReport,
    VerificationClaim,
)
from app.schemas.enums import (
    ClaimVerificationResult,
    FactCheckOverallResult,
    SpecialCheckResult,
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


def special_report(
    *, article_id: str = "ARTICLE_001", article_version: int = 1
) -> SpecialCheckReport:
    return SpecialCheckReport(
        report_id="SC_001",
        task_id="TASK_TEST",
        article_id=article_id,
        article_version=article_version,
        result=SpecialCheckResult.PASSED,
        summary="未发现内容规范或敏感信息问题。",
    )


def delivery_package(
    *,
    article_id: str = "ARTICLE_001",
    article_version: int = 1,
    special_check_report_id: str = "SC_001",
) -> DeliveryPackage:
    return DeliveryPackage(
        package_id="DLV_001",
        task_id="TASK_TEST",
        article_id=article_id,
        article_version=article_version,
        fact_check_report_id="RPT_001",
        special_check_report_id=special_check_report_id,
        source_ids=["SRC_001"],
    )


def test_state_defaults():
    state = make_state()

    assert state.task_status == TaskStatus.CREATED
    assert state.current_stage == WorkflowStage.CREATED
    assert state.paused is False
    assert state.revision_round == 0
    assert state.interface_retry_counts == {}
    assert state.research_sources == []
    assert state.execution_logs == []
    assert state.delivery_package is None
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


def test_special_check_report_requires_task_binding():
    with pytest.raises(ValidationError, match="task_id"):
        make_state(
            task_id="TASK_OTHER",
            article_id="ARTICLE_001",
            article_version=1,
            special_check_report=special_report(),
        )


def test_pending_review_requires_delivery_package():
    with pytest.raises(ValidationError, match="delivery_package"):
        make_state(
            task_status=TaskStatus.PENDING_REVIEW,
            article_id="ARTICLE_001",
            article_version=1,
            fact_check_report=passed_report(),
            special_check_report=special_report(),
        )


def test_delivered_accepts_bound_delivery_package():
    state = make_state(
        task_status=TaskStatus.DELIVERED,
        current_stage=WorkflowStage.DELIVERED,
        article_id="ARTICLE_001",
        article_version=1,
        fact_check_report=passed_report(),
        special_check_report=special_report(),
        delivery_package=delivery_package(),
    )

    assert state.task_status == TaskStatus.DELIVERED
    assert state.delivery_package.package_id == "DLV_001"


def test_delivery_package_report_ids_must_match_current_reports():
    with pytest.raises(ValidationError, match="special_check_report_id"):
        make_state(
            task_status=TaskStatus.PENDING_REVIEW,
            article_id="ARTICLE_001",
            article_version=1,
            fact_check_report=passed_report(),
            special_check_report=special_report(),
            delivery_package=delivery_package(special_check_report_id="SC_OTHER"),
        )
