import pytest
from pydantic import ValidationError

from app.agents.contracts import (
    AGENT_CONTRACTS,
    ChiefPlanningOutput,
    ChiefReviewOutput,
    DeliveryPreparationInput,
    EditorOutput,
    FactCheckerOutput,
    PublisherInput,
    PublisherOutput,
    ReporterOutput,
    SpecialCheckOutput,
)
from app.schemas.domain import (
    ArticleContent,
    EditingReport,
    EditorialPlan,
    ErrorInfo,
    FactCheckFinding,
    FactCheckReport,
    Publication,
    ResearchSource,
    RevisionRequest,
    SourceEvidence,
    SpecialCheckFinding,
    SpecialCheckIssue,
    SpecialCheckReport,
    VerificationClaim,
)
from app.schemas.enums import (
    AgentStatus,
    ChiefDecision,
    ClaimVerificationResult,
    FactCheckOverallResult,
    RevisionTarget,
    SpecialCheckResult,
    SpecialCheckSeverity,
)


def plan() -> EditorialPlan:
    return EditorialPlan(
        topic_analysis="分析",
        reporting_angles=["角度一"],
        research_tasks=["搜集资料"],
        article_outline=["背景", "结论"],
        verification_points=["数据真实性"],
    )


def article() -> ArticleContent:
    return ArticleContent(title="新闻标题", content="新闻正文")


def revision(target: RevisionTarget = RevisionTarget.EDITOR) -> RevisionRequest:
    return RevisionRequest(
        target=target,
        reason="需要调整",
        requirements=["补充说明"],
    )


def verified_claim() -> VerificationClaim:
    return VerificationClaim(
        claim="某项事实",
        result=ClaimVerificationResult.VERIFIED,
        evidence=[
            SourceEvidence(
                source_id="SRC_001",
                url="https://example.com/a",
                supporting_excerpt="来源中的证据",
            )
        ],
        reason="有来源支持",
    )


def unverified_claim() -> VerificationClaim:
    return VerificationClaim(
        claim="某项无法核实的事实",
        result=ClaimVerificationResult.UNVERIFIED,
        reason="未找到可靠来源",
    )


def finding(
    result: FactCheckOverallResult = FactCheckOverallResult.PASSED,
    claims: list[VerificationClaim] | None = None,
) -> FactCheckFinding:
    return FactCheckFinding(
        overall_result=result,
        claims=claims if claims is not None else [verified_claim()],
    )


def test_planning_completed_requires_plan():
    with pytest.raises(ValidationError, match="editorial_plan"):
        ChiefPlanningOutput()


def test_failed_output_requires_error():
    with pytest.raises(ValidationError, match="error is required"):
        ChiefPlanningOutput(status=AgentStatus.FAILED)


def test_failed_output_allows_missing_payload():
    output = ChiefPlanningOutput(
        status=AgentStatus.FAILED,
        error=ErrorInfo(code="LLM_TIMEOUT", message="模型调用超时", retryable=True),
    )

    assert output.editorial_plan is None


def test_completed_output_rejects_error():
    with pytest.raises(ValidationError, match="error must be None"):
        ChiefPlanningOutput(
            editorial_plan=plan(),
            error=ErrorInfo(code="X", message="不应出现"),
        )


def test_source_url_must_be_http():
    with pytest.raises(ValidationError, match="url"):
        ResearchSource(source_id="SRC_001", title="来源", url="example.com/a")


def test_reporter_completed_requires_sources():
    with pytest.raises(ValidationError, match="sources"):
        ReporterOutput(draft=article(), research_summary="资料总结")


def test_editor_requires_new_version():
    with pytest.raises(ValidationError, match="greater than or equal to 2"):
        EditorOutput(
            edited_article=article(),
            editing_report=EditingReport(
                structure_changes="调整结构",
                language_changes="优化表达",
                content_changes="修正措辞",
            ),
            version=1,
        )


def test_fact_checker_completed_requires_article_binding():
    with pytest.raises(ValidationError, match="article_id"):
        FactCheckerOutput(verification_report=finding())


def test_fact_checker_completed_output_is_valid():
    output = FactCheckerOutput(
        verification_report=finding(),
        article_id="ARTICLE_001",
        article_version=1,
    )

    assert output.verification_report.overall_result == FactCheckOverallResult.PASSED


def test_verified_claim_requires_evidence():
    with pytest.raises(ValidationError, match="evidence"):
        VerificationClaim(
            claim="某项事实",
            result=ClaimVerificationResult.VERIFIED,
            reason="声称有来源",
        )


def test_passed_report_rejects_unverified_claim():
    with pytest.raises(ValidationError, match="PASSED"):
        finding(FactCheckOverallResult.PASSED, [unverified_claim()])


def test_failed_report_requires_problem_claim():
    with pytest.raises(ValidationError, match="FAILED"):
        finding(FactCheckOverallResult.FAILED, [verified_claim()])


def test_chief_review_request_edit_requires_revision():
    with pytest.raises(ValidationError, match="REQUEST_EDIT requires revision_request"):
        ChiefReviewOutput(
            chief_decision=ChiefDecision.REQUEST_EDIT,
            review_comments="结构需要调整",
        )


def test_chief_review_revision_target_must_match():
    with pytest.raises(ValidationError, match="target=reporter"):
        ChiefReviewOutput(
            chief_decision=ChiefDecision.REQUEST_RESEARCH,
            review_comments="资料不足",
            revision_request=revision(RevisionTarget.EDITOR),
        )


def test_chief_review_approve_rejects_revision():
    with pytest.raises(ValidationError, match="APPROVE"):
        ChiefReviewOutput(
            chief_decision=ChiefDecision.APPROVE,
            review_comments="通过",
            revision_request=revision(),
        )


def test_chief_review_human_review_is_valid():
    output = ChiefReviewOutput(
        chief_decision=ChiefDecision.HUMAN_REVIEW,
        review_comments="关键信息存在争议，转人工",
    )

    assert output.revision_request is None


def test_publisher_rejects_unapproved_article():
    with pytest.raises(ValidationError, match="chief_decision=APPROVE"):
        PublisherInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=article(),
            article_version=1,
            chief_decision=ChiefDecision.REQUEST_EDIT,
            fact_check_status=FactCheckOverallResult.PASSED,
        )


def test_publisher_rejects_failed_fact_check():
    with pytest.raises(ValidationError, match="fact check"):
        PublisherInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=article(),
            article_version=1,
            chief_decision=ChiefDecision.APPROVE,
            fact_check_status=FactCheckOverallResult.FAILED,
        )


def test_publisher_output_defaults_to_pending_publish():
    output = PublisherOutput(
        publication=Publication(article_id="ARTICLE_001", article_version=1)
    )

    assert output.publication.status == "PENDING_PUBLISH"


def make_special(
    result: SpecialCheckResult = SpecialCheckResult.PASSED,
) -> SpecialCheckReport:
    issues = (
        [
            SpecialCheckIssue(
                category="敏感信息",
                severity=SpecialCheckSeverity.BLOCKING,
                description="包含敏感信息。",
            )
        ]
        if result == SpecialCheckResult.BLOCKED
        else []
    )
    return SpecialCheckReport(
        report_id="SC_001",
        task_id="TASK_001",
        article_id="ARTICLE_001",
        article_version=1,
        result=result,
        summary="专项检查结论",
        issues=issues,
    )


def test_blocked_special_finding_requires_blocking_issue():
    with pytest.raises(ValidationError, match="BLOCKING"):
        SpecialCheckFinding(
            result=SpecialCheckResult.BLOCKED,
            summary="结论为阻断但缺少阻断项",
        )


def test_special_check_output_completed_requires_binding():
    with pytest.raises(ValidationError, match="article_id"):
        SpecialCheckOutput(
            finding=SpecialCheckFinding(
                result=SpecialCheckResult.PASSED, summary="通过"
            )
        )


def test_delivery_rejects_failed_fact_check():
    with pytest.raises(ValidationError, match="FAILED fact check"):
        DeliveryPreparationInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=article(),
            article_version=1,
            fact_check_report=FactCheckReport(
                report_id="FC_001",
                article_id="ARTICLE_001",
                article_version=1,
                overall_result=FactCheckOverallResult.FAILED,
                claims=[unverified_claim()],
            ),
            special_check_report=make_special(),
        )


def test_delivery_rejects_blocked_special_check():
    with pytest.raises(ValidationError, match="BLOCKED special check"):
        DeliveryPreparationInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=article(),
            article_version=1,
            fact_check_report=FactCheckReport(
                report_id="FC_001",
                article_id="ARTICLE_001",
                article_version=1,
                overall_result=FactCheckOverallResult.PASSED,
                claims=[verified_claim()],
            ),
            special_check_report=make_special(SpecialCheckResult.BLOCKED),
        )


def test_agent_contract_registry_covers_workflow_nodes():
    assert set(AGENT_CONTRACTS) == {
        "chief_planning",
        "reporter",
        "editor",
        "fact_checker",
        "special_check",
        "chief_review",
        "prepare_delivery",
    }
