import asyncio

from app.agents.chief_editor import ChiefReviewAgent
from app.agents.contracts import ChiefReviewInput
from app.schemas.domain import (
    FactCheckReport,
    SourceEvidence,
    VerificationClaim,
)
from app.schemas.enums import (
    AgentStatus,
    ChiefDecision,
    ClaimVerificationResult,
    FactCheckOverallResult,
    RevisionTarget,
)
from tests.fakes import FakeLLM, make_article, make_plan, make_requirements, make_source


def evidence() -> list[SourceEvidence]:
    return [
        SourceEvidence(
            source_id="SRC_0001",
            url="https://example.com/a",
            supporting_excerpt="来源摘要",
        )
    ]


def make_report(overall: FactCheckOverallResult) -> FactCheckReport:
    if overall == FactCheckOverallResult.PASSED:
        claims = [
            VerificationClaim(
                claim="断言一",
                result=ClaimVerificationResult.VERIFIED,
                evidence=evidence(),
                reason="证据支持",
            )
        ]
    elif overall == FactCheckOverallResult.PARTIAL:
        claims = [
            VerificationClaim(
                claim="断言一",
                result=ClaimVerificationResult.VERIFIED,
                evidence=evidence(),
                reason="证据支持",
            ),
            VerificationClaim(
                claim="断言二",
                result=ClaimVerificationResult.UNVERIFIED,
                reason="找不到证据",
            ),
        ]
    else:
        claims = [
            VerificationClaim(
                claim="断言一",
                result=ClaimVerificationResult.CONTRADICTED,
                evidence=evidence(),
                reason="与来源矛盾",
            )
        ]
    return FactCheckReport(
        report_id="FC_0001",
        article_id="ART_0001",
        article_version=2,
        overall_result=overall,
        claims=claims,
        issues=[],
    )


def make_input(
    overall: FactCheckOverallResult = FactCheckOverallResult.PASSED,
    *,
    retry_count: int = 0,
    max_retry: int = 2,
) -> ChiefReviewInput:
    return ChiefReviewInput(
        task_id="TASK_001",
        topic="人工智能在高校教育中的应用",
        description="关注教学实践",
        requirements=make_requirements(),
        editorial_plan=make_plan(),
        sources=[make_source()],
        edited_article=make_article(),
        article_id="ART_0001",
        article_version=2,
        fact_check_report=make_report(overall),
        retry_count=retry_count,
        max_retry=max_retry,
    )


def run_agent(agent: ChiefReviewAgent, payload: ChiefReviewInput):
    return asyncio.run(agent.run(payload))


APPROVE = {
    "chief_decision": "APPROVE",
    "review_comments": "事实核查全部通过，稿件符合报道要求，可以进入发布流程。",
}
REQUEST_EDIT = {
    "chief_decision": "REQUEST_EDIT",
    "review_comments": "文章结构松散，需要重新组织段落。",
    "revision_reason": "结构不符合要求",
    "revision_requirements": ["合并重复段落", "补充背景说明"],
    "related_claims": ["断言一"],
}
REQUEST_RESEARCH = {
    "chief_decision": "REQUEST_RESEARCH",
    "review_comments": "关键数据缺少可靠来源，需要补充资料。",
    "revision_reason": "资料不足",
    "revision_requirements": ["补充官方统计数据"],
}
HUMAN_REVIEW = {
    "chief_decision": "HUMAN_REVIEW",
    "review_comments": "核心事实存在争议，需要人工判断。",
    "revision_reason": "存在争议",
    "revision_requirements": ["请人工确认"],
}


def test_review_approves_passed_article():
    output = run_agent(ChiefReviewAgent(llm=FakeLLM([APPROVE])), make_input())

    assert output.status == AgentStatus.COMPLETED
    assert output.chief_decision == ChiefDecision.APPROVE
    assert output.revision_request is None
    assert output.review_comments


def test_review_downgrades_approve_when_fact_check_partial():
    output = run_agent(
        ChiefReviewAgent(llm=FakeLLM([APPROVE])),
        make_input(FactCheckOverallResult.PARTIAL),
    )

    assert output.chief_decision == ChiefDecision.HUMAN_REVIEW
    assert output.revision_request is None
    assert "系统已转为人工审核" in output.review_comments


def test_review_downgrades_approve_when_fact_check_failed():
    output = run_agent(
        ChiefReviewAgent(llm=FakeLLM([APPROVE])),
        make_input(FactCheckOverallResult.FAILED),
    )

    assert output.chief_decision == ChiefDecision.HUMAN_REVIEW
    assert "系统已转为人工审核" in output.review_comments


def test_review_builds_editor_revision_request():
    output = run_agent(ChiefReviewAgent(llm=FakeLLM([REQUEST_EDIT])), make_input())

    assert output.chief_decision == ChiefDecision.REQUEST_EDIT
    revision = output.revision_request
    assert revision is not None
    assert revision.target == RevisionTarget.EDITOR
    assert revision.requirements == ["合并重复段落", "补充背景说明"]
    assert revision.related_claims == ["断言一"]


def test_review_builds_reporter_revision_request():
    output = run_agent(ChiefReviewAgent(llm=FakeLLM([REQUEST_RESEARCH])), make_input())

    assert output.chief_decision == ChiefDecision.REQUEST_RESEARCH
    assert output.revision_request is not None
    assert output.revision_request.target == RevisionTarget.REPORTER


def test_review_rejects_revision_without_requirements():
    incomplete = {
        "chief_decision": "REQUEST_EDIT",
        "review_comments": "需要修改结构。",
        "revision_reason": "结构问题",
    }
    llm = FakeLLM([incomplete, incomplete])
    output = run_agent(ChiefReviewAgent(llm=llm), make_input())

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "LLM_OUTPUT_INVALID"
    assert len(llm.calls) == 2


def test_review_forces_human_review_when_retry_budget_exhausted():
    output = run_agent(
        ChiefReviewAgent(llm=FakeLLM([REQUEST_RESEARCH])),
        make_input(retry_count=2, max_retry=2),
    )

    assert output.status == AgentStatus.COMPLETED
    assert output.chief_decision == ChiefDecision.HUMAN_REVIEW
    assert output.revision_request is None
    assert "退回次数已达上限" in output.review_comments


def test_review_human_review_ignores_revision_fields():
    output = run_agent(ChiefReviewAgent(llm=FakeLLM([HUMAN_REVIEW])), make_input())

    assert output.chief_decision == ChiefDecision.HUMAN_REVIEW
    assert output.revision_request is None
