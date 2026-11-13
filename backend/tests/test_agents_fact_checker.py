import asyncio

from app.agents.contracts import FactCheckerInput
from app.agents.fact_checker import FactCheckerAgent
from app.schemas.enums import (
    AgentStatus,
    ChiefDecision,
    ClaimVerificationResult,
    FactCheckOverallResult,
)
from app.tools.search import SearchError, SearchNotConfiguredError
from tests.fakes import FakeLLM, FakeSearch, make_article, make_hit, make_source


def run_agent(agent: FactCheckerAgent, payload: FactCheckerInput):
    return asyncio.run(agent.run(payload))


def verdict(claim: str, result: str, evidence_ids: list[str]) -> dict:
    return {
        "claim": claim,
        "result": result,
        "reason": "根据证据判断",
        "evidence_ids": evidence_ids,
    }


def test_fact_checker_binds_evidence_and_passes():
    llm = FakeLLM(
        [
            {"claims": ["断言 A", "断言 B"]},
            {
                "claims": [
                    verdict("断言 A", "VERIFIED", ["SRC_0001"]),
                    verdict("断言 B", "VERIFIED", ["EVID_0001"]),
                ],
                "issues": [],
            },
        ]
    )
    search = FakeSearch(
        default=[
            make_hit(
                "核查证据",
                url="https://evidence.example.com/a",
                summary="证据摘要，明确支持该断言。",
            )
        ]
    )
    agent = FactCheckerAgent(llm=llm, search=search)

    output = run_agent(
        agent,
        FactCheckerInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=make_article(),
            article_version=2,
            sources=[make_source("SRC_0001")],
        ),
    )

    assert output.status == AgentStatus.COMPLETED
    assert output.article_id == "ARTICLE_001"
    assert output.article_version == 2
    report = output.verification_report
    assert report is not None
    assert report.overall_result == FactCheckOverallResult.PASSED
    assert report.recommendation == ChiefDecision.APPROVE
    assert [claim.result for claim in report.claims] == [
        ClaimVerificationResult.VERIFIED,
        ClaimVerificationResult.VERIFIED,
    ]
    assert report.claims[0].evidence[0].url == "https://example.com/article"
    assert report.claims[1].evidence[0].url == "https://evidence.example.com/a"
    assert "证据摘要" in report.claims[1].evidence[0].supporting_excerpt
    assert set(search.queries) == {"断言 A", "断言 B"}

    verify_prompt = llm.calls[1]["user"]
    assert "https://evidence.example.com/a" in verify_prompt
    assert "SRC_0001" in verify_prompt


def test_fact_checker_reports_contradiction_as_failed():
    llm = FakeLLM(
        [
            {"claims": ["断言 A"]},
            {
                "claims": [
                    verdict("断言 A", "CONTRADICTED", ["EVID_0001"])
                ],
                "issues": ["来源与稿件数据矛盾"],
            },
        ]
    )
    agent = FactCheckerAgent(llm=llm, search=FakeSearch(default=[make_hit()]))

    output = run_agent(
        agent,
        FactCheckerInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=make_article(),
            article_version=1,
        ),
    )

    assert output.verification_report is not None
    report = output.verification_report
    assert report.overall_result == FactCheckOverallResult.FAILED
    assert report.recommendation == ChiefDecision.REQUEST_RESEARCH
    assert report.issues == ["来源与稿件数据矛盾"]


def test_fact_checker_downgrades_unknown_evidence_to_unverified():
    llm = FakeLLM(
        [
            {"claims": ["断言 A", "断言 B"]},
            {
                "claims": [
                    verdict("断言 A", "VERIFIED", ["UNKNOWN_1"]),
                    verdict("断言 B", "VERIFIED", ["EVID_0001"]),
                ],
                "issues": [],
            },
        ]
    )
    agent = FactCheckerAgent(llm=llm, search=FakeSearch(default=[make_hit()]))

    output = run_agent(
        agent,
        FactCheckerInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=make_article(),
            article_version=1,
        ),
    )

    assert output.verification_report is not None
    report = output.verification_report
    assert report.overall_result == FactCheckOverallResult.PARTIAL
    assert report.claims[0].result == ClaimVerificationResult.UNVERIFIED
    assert report.claims[0].evidence == []
    assert report.claims[1].result == ClaimVerificationResult.VERIFIED
    assert any("未知来源编号" in issue for issue in report.issues)
    assert any("缺少有效证据" in issue for issue in report.issues)


def test_fact_checker_marks_missing_verdict_as_unverified():
    llm = FakeLLM(
        [
            {"claims": ["断言 A", "断言 B"]},
            {
                "claims": [verdict("断言 A", "VERIFIED", ["EVID_0001"])],
                "issues": ["模型未能判断断言 B"],
            },
        ]
    )
    agent = FactCheckerAgent(llm=llm, search=FakeSearch(default=[make_hit()]))

    output = run_agent(
        agent,
        FactCheckerInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=make_article(),
            article_version=1,
        ),
    )

    assert output.verification_report is not None
    report = output.verification_report
    assert report.overall_result == FactCheckOverallResult.PARTIAL
    assert report.claims[1].result == ClaimVerificationResult.UNVERIFIED
    assert any("未返回断言" in issue for issue in report.issues)
    assert "模型未能判断断言 B" in report.issues


def test_fact_checker_uses_article_sources_when_search_is_empty():
    llm = FakeLLM(
        [
            {"claims": ["断言 A"]},
            {
                "claims": [verdict("断言 A", "VERIFIED", ["SRC_0001"])],
                "issues": [],
            },
        ]
    )
    agent = FactCheckerAgent(llm=llm, search=FakeSearch(default=[]))

    output = run_agent(
        agent,
        FactCheckerInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=make_article(),
            article_version=1,
            sources=[make_source("SRC_0001")],
        ),
    )

    assert output.verification_report is not None
    report = output.verification_report
    assert report.overall_result == FactCheckOverallResult.PASSED
    assert report.claims[0].evidence[0].source_id == "SRC_0001"


def test_fact_checker_fails_when_all_searches_fail():
    llm = FakeLLM([{"claims": ["断言 A", "断言 B"]}])
    agent = FactCheckerAgent(
        llm=llm,
        search=FakeSearch(error=SearchError("搜索服务不可用", retryable=True)),
    )

    output = run_agent(
        agent,
        FactCheckerInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=make_article(),
            article_version=1,
        ),
    )

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "SEARCH_FAILED"
    assert output.error.retryable is True
    assert len(llm.calls) == 1


def test_fact_checker_maps_search_configuration_error():
    llm = FakeLLM([{"claims": ["断言 A"]}])
    agent = FactCheckerAgent(
        llm=llm,
        search=FakeSearch(error=SearchNotConfiguredError()),
    )

    output = run_agent(
        agent,
        FactCheckerInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=make_article(),
            article_version=1,
        ),
    )

    assert output.error is not None
    assert output.error.code == "SEARCH_NOT_CONFIGURED"


def test_fact_checker_fails_after_empty_claim_retry():
    llm = FakeLLM([{"claims": []}, {"claims": []}])
    agent = FactCheckerAgent(llm=llm, search=FakeSearch(default=[]))

    output = run_agent(
        agent,
        FactCheckerInput(
            task_id="TASK_001",
            article_id="ARTICLE_001",
            article=make_article(),
            article_version=1,
        ),
    )

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "LLM_OUTPUT_INVALID"
    assert len(llm.calls) == 2
    assert "未通过校验" in llm.calls[1]["user"]
