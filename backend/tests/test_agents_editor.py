import asyncio

from app.agents.contracts import EditorInput
from app.agents.editor import EditorAgent
from app.core.llm import LLMError
from app.schemas.domain import (
    FactCheckReport,
    RevisionRequest,
    VerificationClaim,
)
from app.schemas.enums import (
    AgentStatus,
    ChiefDecision,
    ClaimVerificationResult,
    FactCheckOverallResult,
    RevisionTarget,
)
from tests.fakes import FakeLLM, make_article, make_requirements

EDITOR_RESPONSE = {
    "title": "人工智能进入高校课堂：案例与挑战",
    "content": "编辑后的新闻正文。",
    "structure_changes": "调整导语与段落顺序",
    "language_changes": "删除夸张表述",
    "content_changes": "保留原有事实，仅优化表达",
}


def run_agent(agent: EditorAgent, payload: EditorInput):
    return asyncio.run(agent.run(payload))


def make_report() -> FactCheckReport:
    return FactCheckReport(
        report_id="RPT_001",
        article_id="ARTICLE_001",
        article_version=2,
        overall_result=FactCheckOverallResult.PARTIAL,
        claims=[
            VerificationClaim(
                claim="某项统计数据",
                result=ClaimVerificationResult.UNVERIFIED,
                reason="缺少可靠来源",
            )
        ],
        issues=["部分统计数据缺少可靠来源"],
        recommendation=ChiefDecision.REQUEST_RESEARCH,
    )


def test_editor_returns_new_version_and_reports_changes():
    llm = FakeLLM([EDITOR_RESPONSE])
    agent = EditorAgent(llm=llm)

    output = run_agent(
        agent,
        EditorInput(
            task_id="TASK_001",
            draft=make_article(),
            requirements=make_requirements(),
            revision_request=RevisionRequest(
                target=RevisionTarget.EDITOR,
                reason="标题不够准确",
                requirements=["标题需与正文事实一致"],
            ),
            review_comments="标题需要更准确",
            fact_check_report=make_report(),
            current_version=2,
        ),
    )

    assert output.status == AgentStatus.COMPLETED
    assert output.version == 3
    assert output.edited_article is not None
    assert output.edited_article.title == EDITOR_RESPONSE["title"]
    assert output.editing_report is not None
    assert output.editing_report.language_changes == "删除夸张表述"

    prompt = llm.calls[0]["user"]
    assert "标题需要更准确" in prompt
    assert "部分统计数据缺少可靠来源" in prompt
    assert "标题需与正文事实一致" in prompt
    assert "客观新闻报道" in prompt


def test_editor_rejects_reporter_revision_target():
    agent = EditorAgent(llm=FakeLLM([]))

    output = run_agent(
        agent,
        EditorInput(
            task_id="TASK_001",
            draft=make_article(),
            revision_request=RevisionRequest(
                target=RevisionTarget.REPORTER,
                reason="资料不足",
                requirements=["补充资料"],
            ),
            current_version=1,
        ),
    )

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "INVALID_REVISION_TARGET"


def test_editor_fails_after_invalid_output_retry():
    llm = FakeLLM(
        [
            {**EDITOR_RESPONSE, "structure_changes": ""},
            {**EDITOR_RESPONSE, "structure_changes": ""},
        ]
    )
    agent = EditorAgent(llm=llm)

    output = run_agent(
        agent,
        EditorInput(task_id="TASK_001", draft=make_article()),
    )

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "LLM_OUTPUT_INVALID"
    assert len(llm.calls) == 2
    assert "未通过校验" in llm.calls[1]["user"]


def test_editor_maps_llm_error():
    agent = EditorAgent(
        llm=FakeLLM([LLMError("LLM_REQUEST_FAILED", "LLM 请求失败", retryable=True)])
    )

    output = run_agent(
        agent,
        EditorInput(task_id="TASK_001", draft=make_article()),
    )

    assert output.error is not None
    assert output.error.code == "LLM_REQUEST_FAILED"
    assert output.error.retryable is True
