import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.graph.nodes import create_default_agents
from app.graph.workflow import NewsroomWorkflow
from app.main import create_app
from app.services.task_store import InMemoryTaskStore
from tests.fakes import FakeLLM, FakeSearch, make_hit

API = "/api/news/tasks"

PLAN = {
    "topic_analysis": "选题分析内容不少于三十个字的说明文本，用于验证执行接口。",
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
HUMAN_REVIEW = {
    "chief_decision": "HUMAN_REVIEW",
    "review_comments": "核心事实存在争议，需要人工判断。",
}

HAPPY_RESPONSES = [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, APPROVE]
HUMAN_RESPONSES = [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, HUMAN_REVIEW]


class SlowLLM(FakeLLM):
    def __init__(self, responses, delay: float = 0.03) -> None:
        super().__init__(responses)
        self.delay = delay

    async def complete_json(self, **kwargs):
        await asyncio.sleep(self.delay)
        return await super().complete_json(**kwargs)


def make_client(responses=None, *, slow: bool = False) -> TestClient:
    llm = (
        SlowLLM(responses or HAPPY_RESPONSES)
        if slow
        else FakeLLM(responses or HAPPY_RESPONSES)
    )
    workflow = NewsroomWorkflow(
        agents=create_default_agents(
            llm=llm, search=FakeSearch(default=[make_hit()])
        )
    )
    app = create_app(task_store=InMemoryTaskStore(), workflow=workflow)
    return TestClient(app)


def create_task(client: TestClient) -> str:
    response = client.post(
        API,
        json={
            "topic": "人工智能在高校教育中的应用",
            "description": "关注教学实践",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["task_id"]


def wait_for_status(client: TestClient, task_id: str, *statuses, timeout=10.0):
    deadline = time.time() + timeout
    detail = None
    while time.time() < deadline:
        response = client.get(f"{API}/{task_id}")
        assert response.status_code == 200, response.text
        detail = response.json()["data"]
        if detail["status"] in statuses:
            return detail
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {statuses}: {detail}")


def test_execute_returns_accepted_then_finishes_in_background():
    with make_client() as client:
        task_id = create_task(client)

        response = client.post(f"{API}/{task_id}/execute")

        assert response.status_code == 202, response.text
        started = response.json()["data"]
        assert started["status"] == "RUNNING"
        assert started["current_stage"] in {
            "created",
            "chief_planning",
            "research",
            "editing",
            "fact_check",
            "special_check",
            "chief_review",
            "prepare_delivery",
        }

        data = wait_for_status(client, task_id, "PENDING_REVIEW")
        assert data["article_version"] == 2
        assert data["latest_special_check"]["result"] == "PASSED"
        assert data["delivery"]["article_version"] == 2


def test_execute_twice_returns_conflict():
    with make_client() as client:
        task_id = create_task(client)
        client.post(f"{API}/{task_id}/execute")
        wait_for_status(client, task_id, "PENDING_REVIEW")

        repeat = client.post(f"{API}/{task_id}/execute")

        assert repeat.status_code == 409
        assert repeat.json()["code"] == 2002


def test_concurrent_execute_returns_busy_code():
    with make_client(slow=True) as client:
        task_id = create_task(client)
        assert client.post(f"{API}/{task_id}/execute").status_code == 202

        second = client.post(f"{API}/{task_id}/execute")

        assert second.status_code == 409
        assert second.json()["code"] == 2003
        wait_for_status(client, task_id, "PENDING_REVIEW")


def test_human_review_approve_and_deliver_flow():
    with make_client(HUMAN_RESPONSES) as client:
        task_id = create_task(client)

        accepted = client.post(f"{API}/{task_id}/execute")
        assert accepted.status_code == 202

        waiting = wait_for_status(client, task_id, "HUMAN_REVIEW")
        assert waiting["article_version"] == 2

        approved = client.post(
            f"{API}/{task_id}/human-review",
            json={"decision": "APPROVE", "comments": "人工确认通过"},
        )
        assert approved.status_code == 202, approved.text
        assert approved.json()["data"]["status"] == "RUNNING"

        data = wait_for_status(client, task_id, "PENDING_REVIEW")
        assert data["delivery"]["article_version"] == 2

        delivery = client.get(f"{API}/{task_id}/delivery")
        assert delivery.status_code == 200
        package = delivery.json()["data"]
        assert package["special_check_report_id"]

        delivered = client.post(
            f"{API}/{task_id}/delivery/confirm", json={"confirmed": True}
        )
        assert delivered.status_code == 200
        assert delivered.json()["data"]["status"] == "DELIVERED"


def test_human_review_validation_error():
    with make_client(HUMAN_RESPONSES) as client:
        task_id = create_task(client)
        client.post(f"{API}/{task_id}/execute")
        wait_for_status(client, task_id, "HUMAN_REVIEW")

        response = client.post(
            f"{API}/{task_id}/human-review",
            json={"decision": "REQUEST_EDIT"},
        )

        assert response.status_code == 400
        assert response.json()["code"] == 1001


def test_human_review_rejects_wrong_status():
    with make_client() as client:
        task_id = create_task(client)

        response = client.post(
            f"{API}/{task_id}/human-review", json={"decision": "APPROVE"}
        )

        assert response.status_code == 409
        assert response.json()["code"] == 2002


def test_pause_and_resume_endpoints():
    with make_client() as client:
        task_id = create_task(client)

        paused = client.post(f"{API}/{task_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["data"]["paused"] is True

        blocked = client.post(f"{API}/{task_id}/execute")
        assert blocked.status_code == 409

        resumed = client.post(f"{API}/{task_id}/resume")
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["data"]["paused"] is False

        data = wait_for_status(client, task_id, "PENDING_REVIEW")
        assert data["delivery"] is not None


def test_delivery_decline_keeps_pending_review():
    with make_client() as client:
        task_id = create_task(client)
        client.post(f"{API}/{task_id}/execute")
        wait_for_status(client, task_id, "PENDING_REVIEW")

        response = client.post(
            f"{API}/{task_id}/delivery/confirm", json={"confirmed": False}
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "PENDING_REVIEW"
        assert response.json()["data"]["delivery"] is not None


def test_delivery_confirm_requires_pending_review():
    with make_client() as client:
        task_id = create_task(client)

        response = client.post(
            f"{API}/{task_id}/delivery/confirm", json={"confirmed": True}
        )

        assert response.status_code == 409
        assert response.json()["code"] == 2002


def test_events_list_returns_execution_logs():
    with make_client() as client:
        task_id = create_task(client)
        client.post(f"{API}/{task_id}/execute")
        wait_for_status(client, task_id, "PENDING_REVIEW")

        response = client.get(f"{API}/{task_id}/events")

        assert response.status_code == 200
        events = response.json()["data"]
        assert len(events) == 7
        assert events[0]["agent_name"] == "chief_editor"
        assert events[-1]["agent_name"] == "delivery_preparer"
        assert all(event["finished_at"] for event in events)


def test_events_for_missing_task_returns_404():
    with make_client() as client:
        response = client.get(f"{API}/TASK_MISSING/events")

        assert response.status_code == 404
        assert response.json()["code"] == 2001
