import asyncio

from app.core.llm import LLMError
from app.graph.nodes import create_default_agents
from app.graph.state import NewsTaskState
from app.graph.workflow import NewsroomWorkflow
from app.schemas.enums import (
    AgentStatus,
    ChiefDecision,
    HumanDecision,
    PublicationStatus,
    TaskStatus,
)
from app.services.publish_service import MockPublishService
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
    "review_comments": "事实核查全部通过，稿件符合报道要求，可以进入发布流程。",
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


def build_workflow(
    responses,
    *,
    search=None,
    publish_service=None,
    max_retry: int = 2,
):
    llm = FakeLLM(responses)
    agents = create_default_agents(
        llm=llm,
        search=search or FakeSearch(default=[make_hit()]),
        publish_service=publish_service,
    )
    workflow = NewsroomWorkflow(agents=agents, max_retry=max_retry)
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


def test_happy_path_waits_for_confirmation_then_publishes():
    workflow, llm = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, APPROVE]
    )
    result = run(workflow)

    assert result.interrupt is not None
    state = result.state
    assert state.task_status == TaskStatus.PENDING_PUBLISH
    assert state.article_version == 2
    assert state.article_id is not None
    assert state.research_sources
    assert state.fact_check_report is not None
    assert state.fact_check_report.article_version == 2
    assert state.publication is not None
    assert state.publication.status == PublicationStatus.PENDING_PUBLISH
    assert state.chief_decision == ChiefDecision.APPROVE

    published = resume(workflow, {"confirm": True})
    assert published.interrupt is None
    assert published.state.task_status == TaskStatus.PUBLISHED
    assert published.state.publication is not None
    assert published.state.publication.status == PublicationStatus.PUBLISHED
    assert published.state.publication.external_url is not None
    assert published.state.user_confirmation is True

    agents = [entry.agent_name.value for entry in published.state.execution_logs]
    assert agents == [
        "chief_editor",
        "reporter",
        "editor",
        "fact_checker",
        "chief_editor",
        "publisher",
        "publisher",
    ]
    assert len(llm.calls) == 7


def test_declining_confirmation_keeps_task_pending():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, APPROVE]
    )
    run(workflow)
    result = resume(workflow, {"confirm": False})

    assert result.state.task_status == TaskStatus.PENDING_PUBLISH
    assert result.state.user_confirmation is False
    assert result.state.publication is not None
    assert result.state.publication.status == PublicationStatus.PENDING_PUBLISH


def test_request_edit_loop_creates_new_version_and_reruns_fact_check():
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
    assert result.interrupt is not None
    assert state.task_status == TaskStatus.PENDING_PUBLISH
    assert state.article_version == 3
    assert state.retry_count == 1
    assert state.fact_check_report is not None
    assert state.fact_check_report.article_version == 3
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
    assert result.interrupt is not None
    assert state.task_status == TaskStatus.PENDING_PUBLISH
    assert state.article_version == 3
    assert state.retry_count == 1
    assert [source.source_id for source in state.research_sources] == ["SRC_0001"]
    assert "修改要求" in llm.calls[8]["user"]


def test_human_review_interrupt_can_approve_then_confirm():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, HUMAN_REVIEW]
    )
    result = run(workflow)

    assert result.state.task_status == TaskStatus.HUMAN_REVIEW
    assert result.interrupt is not None
    assert result.interrupt["chief_decision"] == "HUMAN_REVIEW"

    approved = resume(
        workflow, {"decision": "APPROVE", "comments": "人工确认通过"}
    )
    assert approved.state.human_decision == HumanDecision.APPROVE
    assert approved.state.task_status == TaskStatus.PENDING_PUBLISH
    assert approved.interrupt is not None

    published = resume(workflow, {"confirm": True})
    assert published.state.task_status == TaskStatus.PUBLISHED


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
    assert result.state.retry_count == 1
    assert result.state.task_status == TaskStatus.PENDING_PUBLISH


def test_human_review_terminate_cancels_task():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, HUMAN_REVIEW]
    )
    run(workflow)
    result = resume(workflow, {"decision": "TERMINATE"})

    assert result.state.task_status == TaskStatus.CANCELLED
    assert result.state.publication is None


def test_retry_cap_forces_human_review():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, REQUEST_RESEARCH],
        max_retry=0,
    )
    result = run(workflow)

    assert result.state.task_status == TaskStatus.HUMAN_REVIEW
    assert result.state.chief_decision == ChiefDecision.HUMAN_REVIEW
    assert result.state.retry_count == 0
    assert result.interrupt is not None


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


def test_publish_failure_keeps_pending_record():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, APPROVE],
        publish_service=MockPublishService(fail_times=1, failure_message="接口超时"),
    )
    run(workflow)
    result = resume(workflow, {"confirm": True})

    state = result.state
    assert state.task_status == TaskStatus.PENDING_PUBLISH
    assert state.error is not None
    assert state.error.code == "PUBLISH_FAILED"
    assert state.publication is not None
    assert state.publication.status == PublicationStatus.PENDING_PUBLISH
    assert "接口超时" in (state.publication.message or "")


def test_checkpoint_state_is_available_after_interrupt():
    workflow, _ = build_workflow(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, APPROVE]
    )
    run(workflow)
    snapshot = asyncio.run(workflow.get_state(TASK_ID))

    assert snapshot is not None
    assert snapshot.state.task_status == TaskStatus.PENDING_PUBLISH
    assert snapshot.interrupt is not None
    assert snapshot.interrupt["article_version"] == 2
