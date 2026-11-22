import asyncio

import pytest

from app.core.errors import BusyError, ConflictError, NotFoundError
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

RESTING = {
    TaskStatus.HUMAN_REVIEW,
    TaskStatus.PENDING_REVIEW,
    TaskStatus.DELIVERED,
    TaskStatus.FAILED,
    TaskStatus.TERMINATED,
}


class SlowLLM(FakeLLM):
    def __init__(self, responses, delay: float = 0.03) -> None:
        super().__init__(responses)
        self.delay = delay

    async def complete_json(self, **kwargs):
        await asyncio.sleep(self.delay)
        return await super().complete_json(**kwargs)


def build_service(responses=None, *, slow: bool = False, max_revision_rounds: int = 2):
    store = InMemoryTaskStore()
    tasks = TaskService(store)
    llm = SlowLLM(responses or HAPPY_RESPONSES) if slow else FakeLLM(
        responses or HAPPY_RESPONSES
    )
    workflow = NewsroomWorkflow(
        agents=create_default_agents(
            llm=llm, search=FakeSearch(default=[make_hit()])
        ),
        max_revision_rounds=max_revision_rounds,
    )
    return ExecutionService(tasks, workflow=workflow), tasks, llm


async def create_task(tasks: TaskService, topic: str = "人工智能在高校教育中的应用"):
    return await tasks.create_task(
        topic=topic,
        description="关注教学实践",
        requirements=TaskRequirements(),
    )


async def wait_for_status(tasks: TaskService, task_id: str, *statuses, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        state = await tasks.get_task(task_id)
        if state.task_status in statuses:
            return state
        await asyncio.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {statuses}")


async def wait_until_paused(service: ExecutionService, tasks: TaskService, task_id: str):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while loop.time() < deadline:
        state = await tasks.get_task(task_id)
        if state.paused and not service.is_running(task_id):
            return state
        await asyncio.sleep(0.01)
    raise AssertionError(f"task {task_id} did not pause")


def test_execute_returns_running_then_reaches_pending_review():
    service, tasks, llm = build_service()

    async def scenario():
        created = await create_task(tasks)
        started = await service.execute(created.task_id)
        assert started.task_status == TaskStatus.RUNNING

        finished = await wait_for_status(
            tasks, created.task_id, TaskStatus.PENDING_REVIEW
        )
        assert finished.current_stage == WorkflowStage.PENDING_REVIEW
        assert finished.delivery_package is not None
        for _ in range(500):
            if not service.is_running(created.task_id):
                break
            await asyncio.sleep(0.01)
        assert not service.is_running(created.task_id)

        events = await service.list_events(created.task_id)
        return finished, events

    finished, events = asyncio.run(scenario())
    assert len(llm.calls) == 7
    assert len(events) == 7
    assert events[0].agent_name.value == "chief_editor"
    assert events[-1].agent_name.value == "delivery_preparer"


def test_execute_rejects_second_start_after_completion():
    service, tasks, _ = build_service()

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        await wait_for_status(tasks, created.task_id, TaskStatus.PENDING_REVIEW)
        with pytest.raises(ConflictError, match="不允许执行"):
            await service.execute(created.task_id)

    asyncio.run(scenario())


def test_execute_rejects_concurrent_start():
    service, tasks, _ = build_service(slow=True)

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        with pytest.raises(BusyError):
            await service.execute(created.task_id)
        await wait_for_status(
            tasks, created.task_id, TaskStatus.PENDING_REVIEW, timeout=10
        )

    asyncio.run(scenario())


def test_execute_missing_task_returns_not_found():
    service, _, _ = build_service()

    async def scenario():
        with pytest.raises(NotFoundError):
            await service.execute("TASK_MISSING")

    asyncio.run(scenario())


def test_pause_before_start_blocks_execute_until_resume():
    service, tasks, _ = build_service()

    async def scenario():
        created = await create_task(tasks)
        paused = await service.pause(created.task_id)
        assert paused.paused is True

        with pytest.raises(ConflictError, match="已暂停"):
            await service.execute(created.task_id)

        resumed = await service.resume(created.task_id)
        assert resumed.paused is False
        assert resumed.task_status == TaskStatus.RUNNING
        finished = await wait_for_status(
            tasks, created.task_id, TaskStatus.PENDING_REVIEW
        )
        return finished

    finished = asyncio.run(scenario())
    assert finished.delivery_package is not None


def test_pause_stops_background_job_at_node_boundary_then_resume_continues():
    service, tasks, _ = build_service(slow=True)

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        await asyncio.sleep(0.05)

        await service.pause(created.task_id)
        paused = await wait_until_paused(service, tasks, created.task_id)
        assert paused.task_status == TaskStatus.RUNNING
        assert paused.current_stage != WorkflowStage.CREATED

        resumed = await service.resume(created.task_id)
        assert resumed.task_status == TaskStatus.RUNNING
        return await wait_for_status(
            tasks, created.task_id, TaskStatus.PENDING_REVIEW, timeout=10
        )

    finished = asyncio.run(scenario())
    assert finished.article_version == 2
    assert finished.delivery_package is not None


def test_pause_rejects_finished_task():
    service, tasks, _ = build_service()

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        await wait_for_status(tasks, created.task_id, TaskStatus.PENDING_REVIEW)
        with pytest.raises(ConflictError, match="不允许暂停"):
            await service.pause(created.task_id)

    asyncio.run(scenario())


def test_human_review_approve_prepares_delivery_then_confirm_delivers():
    service, tasks, _ = build_service(HUMAN_RESPONSES)

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        waiting = await wait_for_status(
            tasks, created.task_id, TaskStatus.HUMAN_REVIEW
        )
        assert waiting.delivery_package is None

        started = await service.submit_human_review(
            created.task_id,
            decision=HumanDecision.APPROVE,
            comments="人工确认通过",
        )
        assert started.task_status == TaskStatus.RUNNING

        approved = await wait_for_status(
            tasks, created.task_id, TaskStatus.PENDING_REVIEW
        )
        package = await service.get_delivery(created.task_id)
        delivered = await service.confirm_delivery(
            created.task_id, confirmed=True
        )
        return approved, package, delivered

    approved, package, delivered = asyncio.run(scenario())
    assert approved.human_decision == HumanDecision.APPROVE
    assert package.article_version == 2
    assert delivered.task_status == TaskStatus.DELIVERED
    assert delivered.current_stage == WorkflowStage.DELIVERED


def test_delivery_decline_keeps_pending_review():
    service, tasks, _ = build_service()

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        await wait_for_status(tasks, created.task_id, TaskStatus.PENDING_REVIEW)
        kept = await service.confirm_delivery(
            created.task_id, confirmed=False
        )
        return kept, await tasks.get_task(created.task_id)

    kept, stored = asyncio.run(scenario())
    assert kept.task_status == TaskStatus.PENDING_REVIEW
    assert stored.task_status == TaskStatus.PENDING_REVIEW
    assert stored.delivery_package is not None


def test_human_review_can_request_edit_and_rerun_pipeline():
    responses = [*HUMAN_RESPONSES, EDIT, EXTRACT, VERIFY, APPROVE]
    service, tasks, _ = build_service(responses)

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        await wait_for_status(tasks, created.task_id, TaskStatus.HUMAN_REVIEW)
        await service.submit_human_review(
            created.task_id,
            decision=HumanDecision.REQUEST_EDIT,
            revision_reason="结构不符合要求",
            revision_requirements=["重写导语"],
        )
        return await wait_for_status(
            tasks, created.task_id, TaskStatus.PENDING_REVIEW
        )

    outcome = asyncio.run(scenario())
    assert outcome.revision_round == 1
    assert outcome.article_version == 3


def test_human_review_can_terminate():
    service, tasks, _ = build_service(HUMAN_RESPONSES)

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        await wait_for_status(tasks, created.task_id, TaskStatus.HUMAN_REVIEW)
        await service.submit_human_review(
            created.task_id, decision=HumanDecision.TERMINATE
        )
        return await wait_for_status(
            tasks, created.task_id, TaskStatus.TERMINATED
        )

    outcome = asyncio.run(scenario())
    assert outcome.current_stage == WorkflowStage.TERMINATED


def test_human_review_requires_pending_interrupt():
    service, tasks, _ = build_service()

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        await wait_for_status(tasks, created.task_id, TaskStatus.PENDING_REVIEW)
        with pytest.raises(ConflictError, match="待人工处理"):
            await service.submit_human_review(
                created.task_id, decision=HumanDecision.APPROVE
            )

    asyncio.run(scenario())


def test_delivery_confirm_requires_pending_review():
    service, tasks, _ = build_service()

    async def scenario():
        created = await create_task(tasks)
        with pytest.raises(ConflictError, match="待复核"):
            await service.confirm_delivery(created.task_id, confirmed=True)
        with pytest.raises(ConflictError, match="尚未生成"):
            await service.get_delivery(created.task_id)

    asyncio.run(scenario())


def test_execute_marks_task_failed_on_runtime_error():
    class BrokenWorkflow:
        async def stream(self, state):
            raise RuntimeError("checkpoint unavailable")
            yield  # pragma: no cover

    tasks = TaskService(InMemoryTaskStore())
    service = ExecutionService(tasks, workflow=BrokenWorkflow())

    async def scenario():
        created = await create_task(tasks)
        await service.execute(created.task_id)
        return await wait_for_status(tasks, created.task_id, TaskStatus.FAILED)

    failed = asyncio.run(scenario())
    assert failed.current_stage == WorkflowStage.ERROR
    assert failed.error is not None
    assert failed.error.code == "RUNTIME_ERROR"
