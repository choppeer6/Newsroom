import asyncio

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.graph.nodes import create_default_agents
from app.graph.workflow import NewsroomWorkflow
from app.schemas.domain import TaskRequirements
from app.schemas.enums import HumanDecision, TaskStatus, WorkflowStage
from app.services.execution_service import ExecutionService
from app.services.task_service import TaskService
from app.services.task_store import InMemoryTaskStore
from tests.fakes import FakeLLM, FakeSearch, make_hit

PLAN = {
    "topic_analysis": "选题分析内容不少于三十个字的说明文本，用于验证执行服务。",
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
HUMAN_REVIEW = {
    "chief_decision": "HUMAN_REVIEW",
    "review_comments": "核心事实存在争议，需要人工判断。",
}

HAPPY_RESPONSES = [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, APPROVE]
HUMAN_RESPONSES = [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, HUMAN_REVIEW]


def build_service(responses=None, *, max_revision_rounds: int = 2):
    store = InMemoryTaskStore()
    tasks = TaskService(store)
    llm = FakeLLM(responses or HAPPY_RESPONSES)
    workflow = NewsroomWorkflow(
        agents=create_default_agents(
            llm=llm, search=FakeSearch(default=[make_hit()])
        ),
        max_revision_rounds=max_revision_rounds,
    )
    return ExecutionService(tasks, workflow=workflow), tasks, llm


def create_task(tasks: TaskService, topic: str = "人工智能在高校教育中的应用"):
    return asyncio.run(
        tasks.create_task(
            topic=topic,
            description="关注教学实践",
            requirements=TaskRequirements(),
        )
    )


def test_execute_runs_to_pending_review_and_persists():
    service, tasks, llm = build_service()
    state = create_task(tasks)

    outcome = asyncio.run(service.execute(state.task_id))

    assert outcome.interrupt is None
    assert outcome.state.task_status == TaskStatus.PENDING_REVIEW
    assert outcome.state.current_stage == WorkflowStage.PENDING_REVIEW
    assert outcome.state.delivery_package is not None
    assert len(llm.calls) == 7

    stored = asyncio.run(tasks.get_task(state.task_id))
    assert stored.task_status == TaskStatus.PENDING_REVIEW
    assert stored.article_version == 2
    assert stored.delivery_package is not None
    events = asyncio.run(service.list_events(state.task_id))
    assert len(events) == 7
    assert events[0].agent_name.value == "chief_editor"


def test_execute_rejects_second_start():
    service, tasks, _ = build_service()
    state = create_task(tasks)
    asyncio.run(service.execute(state.task_id))

    with pytest.raises(ConflictError, match="不允许执行"):
        asyncio.run(service.execute(state.task_id))


def test_execute_missing_task_returns_not_found():
    service, _, _ = build_service()

    with pytest.raises(NotFoundError):
        asyncio.run(service.execute("TASK_MISSING"))


def test_pause_blocks_execute_until_resume():
    service, tasks, _ = build_service()
    state = create_task(tasks)

    paused = asyncio.run(service.pause(state.task_id))
    assert paused.paused is True
    assert paused.task_status == TaskStatus.CREATED

    with pytest.raises(ConflictError, match="已暂停"):
        asyncio.run(service.execute(state.task_id))

    outcome = asyncio.run(service.resume(state.task_id))
    assert outcome.state.paused is False
    assert outcome.state.task_status == TaskStatus.PENDING_REVIEW


def test_pause_rejects_finished_task():
    service, tasks, _ = build_service()
    state = create_task(tasks)
    asyncio.run(service.execute(state.task_id))

    with pytest.raises(ConflictError, match="不允许暂停"):
        asyncio.run(service.pause(state.task_id))


def test_pause_rejects_while_execution_lock_is_held():
    service, tasks, _ = build_service()
    state = create_task(tasks)

    async def scenario():
        assert await tasks.try_acquire_lock(
            state.task_id, "external", ttl_seconds=60
        )
        try:
            with pytest.raises(ConflictError, match="正在执行"):
                await service.pause(state.task_id)
        finally:
            await tasks.release_lock(state.task_id, "external")

    asyncio.run(scenario())


def test_human_review_approve_prepares_delivery_then_confirm_delivers():
    service, tasks, _ = build_service(HUMAN_RESPONSES)
    state = create_task(tasks)

    waiting = asyncio.run(service.execute(state.task_id))
    assert waiting.state.task_status == TaskStatus.HUMAN_REVIEW
    assert waiting.interrupt is not None
    assert waiting.interrupt["special_check_result"] == "PASSED"

    approved = asyncio.run(
        service.submit_human_review(
            state.task_id,
            decision=HumanDecision.APPROVE,
            comments="人工确认通过",
        )
    )
    assert approved.state.task_status == TaskStatus.PENDING_REVIEW
    assert approved.state.human_decision == HumanDecision.APPROVE
    assert approved.state.delivery_package is not None

    package = asyncio.run(service.get_delivery(state.task_id))
    assert package.article_version == 2

    delivered = asyncio.run(
        service.confirm_delivery(state.task_id, confirmed=True)
    )
    assert delivered.task_status == TaskStatus.DELIVERED
    assert delivered.current_stage == WorkflowStage.DELIVERED


def test_delivery_decline_keeps_pending_review():
    service, tasks, _ = build_service()
    state = create_task(tasks)
    asyncio.run(service.execute(state.task_id))

    kept = asyncio.run(service.confirm_delivery(state.task_id, confirmed=False))

    assert kept.task_status == TaskStatus.PENDING_REVIEW
    stored = asyncio.run(tasks.get_task(state.task_id))
    assert stored.task_status == TaskStatus.PENDING_REVIEW
    assert stored.delivery_package is not None


def test_human_review_can_request_edit_and_rerun_pipeline():
    responses = [
        *HUMAN_RESPONSES,
        EDIT,
        EXTRACT,
        VERIFY,
        APPROVE,
    ]
    service, tasks, _ = build_service(responses)
    state = create_task(tasks)
    asyncio.run(service.execute(state.task_id))

    outcome = asyncio.run(
        service.submit_human_review(
            state.task_id,
            decision=HumanDecision.REQUEST_EDIT,
            revision_reason="结构不符合要求",
            revision_requirements=["重写导语"],
        )
    )

    assert outcome.state.task_status == TaskStatus.PENDING_REVIEW
    assert outcome.state.revision_round == 1
    assert outcome.state.article_version == 3


def test_human_review_can_terminate():
    service, tasks, _ = build_service(HUMAN_RESPONSES)
    state = create_task(tasks)
    asyncio.run(service.execute(state.task_id))

    outcome = asyncio.run(
        service.submit_human_review(
            state.task_id, decision=HumanDecision.TERMINATE
        )
    )

    assert outcome.state.task_status == TaskStatus.TERMINATED
    assert outcome.state.current_stage == WorkflowStage.TERMINATED


def test_human_review_requires_pending_interrupt():
    service, tasks, _ = build_service()
    state = create_task(tasks)
    asyncio.run(service.execute(state.task_id))

    with pytest.raises(ConflictError, match="待人工处理"):
        asyncio.run(
            service.submit_human_review(
                state.task_id, decision=HumanDecision.APPROVE
            )
        )


def test_delivery_confirm_requires_pending_review():
    service, tasks, _ = build_service()
    state = create_task(tasks)

    with pytest.raises(ConflictError, match="待复核"):
        asyncio.run(service.confirm_delivery(state.task_id, confirmed=True))
    with pytest.raises(ConflictError, match="尚未生成"):
        asyncio.run(service.get_delivery(state.task_id))


def test_execute_marks_task_failed_on_runtime_error():
    class BrokenWorkflow:
        async def run(self, state):
            raise RuntimeError("checkpoint unavailable")

    store = InMemoryTaskStore()
    tasks = TaskService(store)
    service = ExecutionService(tasks, workflow=BrokenWorkflow())
    state = create_task(tasks)

    outcome = asyncio.run(service.execute(state.task_id))

    assert outcome.state.task_status == TaskStatus.FAILED
    assert outcome.state.current_stage == WorkflowStage.ERROR
    assert outcome.state.error is not None
    assert outcome.state.error.code == "RUNTIME_ERROR"
    stored = asyncio.run(tasks.get_task(state.task_id))
    assert stored.task_status == TaskStatus.FAILED
