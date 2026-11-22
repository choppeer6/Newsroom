import asyncio
from dataclasses import replace

from app.agents.contracts import SpecialCheckOutput
from app.agents.special_check import SpecialCheckAgent
from app.core.llm import LLMError
from app.graph.nodes import create_default_agents
from app.graph.state import NewsTaskState
from app.graph.workflow import NewsroomWorkflow
from app.schemas.domain import SpecialCheckFinding, SpecialCheckIssue
from app.schemas.enums import (
    AgentStatus,
    ChiefDecision,
    HumanDecision,
    SpecialCheckResult,
    SpecialCheckSeverity,
    TaskStatus,
    WorkflowStage,
)
from app.tools.search import SearchError
from tests.fakes import FakeLLM, FakeSearch, make_hit, make_requirements

PLAN = {
    "topic_analysis": "选题分析内容不少于三十个字的说明文本，用于验证工作流。",
    "reporting_angles": ["应用案例", "教学效果"],
    "research_tasks": ["搜集高校案例"],
    "article_outline": ["背景", "现状", "总结"],
    "verification_points": ["案例真实性"],
}
QUERIES = {"queries": ["高校人工智能案例"]}
DRAFT = {
    "title": "人工智能进入高校课堂",
    "content": "某高校已经开展人工智能教学实践，相关数据正在统计中。",
    "research_summary": "检索发现多所高校已开展人工智能教学实践。",
    "unverified_claims": [],
}
EDIT = {
    "title": "人工智能进入高校课堂",
    "content": "某高校已开展人工智能教学实践，相关数据正在统计中。",
    "structure_changes": "调整导语",
    "language_changes": "精简表达",
    "content_changes": "无事实改动",
}
EXTRACT = {"claims": ["某高校已经开展人工智能教学实践。"]}
VERIFY = {
    "claims": [
        {
            "claim": "某高校已经开展人工智能教学实践。",
            "result": "VERIFIED",
            "reason": "来源摘要支持该说法",
            "evidence_ids": ["SRC_0001"],
        }
    ],
    "issues": [],
}
APPROVE = {
    "chief_decision": "APPROVE",
    "review_comments": "事实核查全部通过，稿件符合报道要求，可以准备交付。",
}
REQUEST_EDIT = {
    "chief_decision": "REQUEST_EDIT",
    "review_comments": "结构需要调整，请按修改要求重写。",
    "revision_reason": "结构松散",
    "revision_requirements": ["合并重复段落"],
}
REQUEST_RESEARCH = {
    "chief_decision": "REQUEST_RESEARCH",
    "review_comments": "关键数据缺少来源，需要补充资料。",
    "revision_reason": "资料不足",
    "revision_requirements": ["补充统计数据来源"],
}
HUMAN_REVIEW = {
    "chief_decision": "HUMAN_REVIEW",
    "review_comments": "核心事实存在争议，需要人工判断。",
}

TASK_ID = "TASK_WF_001"


class BlockedSpecialCheckAgent(SpecialCheckAgent):
    async def run(self, payload):
        return SpecialCheckOutput(
            finding=SpecialCheckFinding(
                result=SpecialCheckResult.BLOCKED,
                summary="发现敏感信息，必须人工处理。",
                issues=[
                    SpecialCheckIssue(
                        category="敏感信息",
                        severity=SpecialCheckSeverity.BLOCKING,
                        description="稿件包含未经核实的个人隐私信息。",
                    )
                ],
            ),
            article_id=payload.article_id,
            article_version=payload.article_version,
        )


def build_workflow(
    responses,
    *,
    search=None,
    max_revision_rounds: int = 2,
    special_checker=None,
):
    llm = FakeLLM(responses)
    agents = create_default_agents(
        llm=llm,
        search=search or FakeSearch(default=[make_hit()]),
    )
    if special_checker is not None:
        agents = replace(agents, special_checker=special_checker)
    workflow = NewsroomWorkflow(
        agents=agents, max_revision_rounds=max_revision_rounds
    )
    return workflow, llm


def make_state(task_id: str = TASK_ID) -> NewsTaskState:
    return NewsTaskState(
        task_id=task_id,
        topic="人工智能在高校教育中的应用",
        requirements=make_requirements(),
    )


def run(workflow: NewsroomWorkflow, task_id: str = TASK_ID):
    return asyncio.run(workflow.run(make_state(task_id)))


def resume(workflow: NewsroomWorkflow, value, task_id: str = TASK_ID):
    return asyncio.run(workflow.resume(task_id, value))


def test_happy_path_prepares_delivery_for_user_review():
    workflow, llm = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, APPROVE]
    )
    result = run(workflow)

    assert result.interrupt is None
    state = result.state
    assert state.task_status == TaskStatus.PENDING_REVIEW
    assert state.current_stage == WorkflowStage.PENDING_REVIEW
    assert state.article_version == 2
    assert state.article_id is not None
    assert state.research_sources
    assert state.fact_check_report is not None
    assert state.fact_check_report.article_version == 2
    assert state.special_check_report is not None
    assert state.special_check_report.result == SpecialCheckResult.PASSED
    assert state.special_check_report.article_version == 2
    assert state.chief_decision == ChiefDecision.APPROVE

    package = state.delivery_package
    assert package is not None
    assert package.article_version == 2
    assert package.fact_check_report_id == state.fact_check_report.report_id
    assert package.special_check_report_id == state.special_check_report.report_id

    agents = [entry.agent_name.value for entry in state.execution_logs]
    assert agents == [
        "chief_editor",
        "reporter",
        "editor",
        "fact_checker",
        "special_checker",
        "chief_editor",
        "delivery_preparer",
    ]
    assert len(llm.calls) == 7


def test_request_edit_loop_creates_new_version_and_reruns_checks():
    workflow, llm = build_workflow(
        [
            PLAN,
            QUERIES,
            DRAFT,
            EDIT,
            EXTRACT,
            VERIFY,
            REQUEST_EDIT,
            EDIT,
            EXTRACT,
            VERIFY,
            APPROVE,
        ]
    )
    result = run(workflow)

    state = result.state
    assert result.interrupt is None
    assert state.task_status == TaskStatus.PENDING_REVIEW
    assert state.article_version == 3
    assert state.revision_round == 1
    assert state.fact_check_report is not None
    assert state.fact_check_report.article_version == 3
    assert state.special_check_report is not None
    assert state.special_check_report.article_version == 3
    assert state.delivery_package is not None
    assert state.delivery_package.article_version == 3
    assert "合并重复段落" in llm.calls[7]["user"]


def test_request_research_loop_reuses_sources_and_reruns_pipeline():
    second_draft = dict(DRAFT, title="人工智能进入高校课堂（修订）")
    workflow, llm = build_workflow(
        [
            PLAN,
            QUERIES,
            DRAFT,
            EDIT,
            EXTRACT,
            VERIFY,
            REQUEST_RESEARCH,
            QUERIES,
            second_draft,
            EDIT,
            EXTRACT,
            VERIFY,
            APPROVE,
        ]
    )
    result = run(workflow)

    state = result.state
    assert result.interrupt is None
    assert state.task_status == TaskStatus.PENDING_REVIEW
    assert state.article_version == 3
    assert state.revision_round == 1
    assert [source.source_id for source in state.research_sources] == ["SRC_0001"]
    assert "修改要求" in llm.calls[8]["user"]


def test_human_review_interrupt_can_approve_then_prepare_delivery():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, HUMAN_REVIEW]
    )
    result = run(workflow)

    assert result.state.task_status == TaskStatus.HUMAN_REVIEW
    assert result.interrupt is not None
    assert result.interrupt["chief_decision"] == "HUMAN_REVIEW"
    assert result.interrupt["special_check_result"] == "PASSED"

    approved = resume(
        workflow, {"decision": "APPROVE", "comments": "人工确认通过"}
    )
    assert approved.interrupt is None
    assert approved.state.human_decision == HumanDecision.APPROVE
    assert approved.state.task_status == TaskStatus.PENDING_REVIEW
    assert approved.state.delivery_package is not None


def test_human_review_can_request_edit():
    workflow, _ = build_workflow(
        [
            PLAN,
            QUERIES,
            DRAFT,
            EDIT,
            EXTRACT,
            VERIFY,
            HUMAN_REVIEW,
            EDIT,
            EXTRACT,
            VERIFY,
            APPROVE,
        ]
    )
    run(workflow)
    result = resume(
        workflow,
        {
            "decision": "REQUEST_EDIT",
            "comments": "人工要求调整结构",
            "revision_reason": "结构不符合要求",
            "revision_requirements": ["重写导语"],
        },
    )

    assert result.state.article_version == 3
    assert result.state.revision_round == 1
    assert result.state.task_status == TaskStatus.PENDING_REVIEW


def test_human_review_terminate_ends_task():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, HUMAN_REVIEW]
    )
    run(workflow)
    result = resume(workflow, {"decision": "TERMINATE"})

    assert result.state.task_status == TaskStatus.TERMINATED
    assert result.state.current_stage == WorkflowStage.TERMINATED
    assert result.state.delivery_package is None


def test_revision_cap_forces_human_review():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, REQUEST_RESEARCH],
        max_revision_rounds=0,
    )
    result = run(workflow)

    assert result.state.task_status == TaskStatus.HUMAN_REVIEW
    assert result.state.chief_decision == ChiefDecision.HUMAN_REVIEW
    assert result.state.revision_round == 0
    assert result.interrupt is not None


def test_blocked_special_check_cannot_be_overridden_by_human_approval():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, APPROVE],
        special_checker=BlockedSpecialCheckAgent(),
    )
    result = run(workflow)

    assert result.state.task_status == TaskStatus.HUMAN_REVIEW
    assert result.state.chief_decision == ChiefDecision.HUMAN_REVIEW
    assert result.interrupt is not None

    approved = resume(workflow, {"decision": "APPROVE", "comments": "希望放行"})
    assert approved.state.task_status == TaskStatus.HUMAN_REVIEW
    assert approved.state.current_stage == WorkflowStage.HUMAN_REVIEW
    assert approved.state.delivery_package is None
    assert "无法准备交付" in (approved.state.review_comments or "")


def test_agent_failure_ends_workflow_with_error():
    workflow, _ = build_workflow(
        [LLMError("LLM_REQUEST_FAILED", "模型请求失败")]
    )
    result = run(workflow)

    state = result.state
    assert result.interrupt is None
    assert state.task_status == TaskStatus.FAILED
    assert state.error is not None
    assert state.error.code == "LLM_REQUEST_FAILED"
    assert state.execution_logs[-1].status == AgentStatus.FAILED


def test_search_failure_ends_workflow_with_error():
    workflow, _ = build_workflow(
        [PLAN, QUERIES],
        search=FakeSearch(error=SearchError("搜索服务不可用")),
    )
    result = run(workflow)

    assert result.state.task_status == TaskStatus.FAILED
    assert result.state.error is not None
    assert result.state.error.code == "SEARCH_FAILED"


def test_checkpoint_state_is_available_after_interrupt():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, HUMAN_REVIEW]
    )
    run(workflow)
    snapshot = asyncio.run(workflow.get_state(TASK_ID))

    assert snapshot is not None
    assert snapshot.state.task_status == TaskStatus.HUMAN_REVIEW
    assert snapshot.interrupt is not None
    assert snapshot.interrupt["article_version"] == 2
