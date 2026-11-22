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


def make_client(responses=None) -> TestClient:
    llm = FakeLLM(responses or HAPPY_RESPONSES)
    workflow = NewsroomWorkflow(
        agents=create_default_agents(
            llm=llm, search=FakeSearch(default=[make_hit()])
        )
    )
    app = create_app(task_store=InMemoryTaskStore(), workflow=workflow)
    return TestClient(app)


@pytest.fixture()
def exec_client():
    with make_client() as client:
        yield client


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


def test_execute_returns_latest_task_detail(exec_client):
    task_id = create_task(exec_client)

    response = exec_client.post(f"{API}/{task_id}/execute")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["task_id"] == task_id
    assert data["status"] == "PENDING_REVIEW"
    assert data["current_stage"] == "pending_review"
    assert data["article_version"] == 2
    assert data["latest_special_check"]["result"] == "PASSED"
    assert data["delivery"]["article_version"] == 2


def test_execute_twice_returns_conflict(exec_client):
    task_id = create_task(exec_client)
    exec_client.post(f"{API}/{task_id}/execute")

    repeat = exec_client.post(f"{API}/{task_id}/execute")

    assert repeat.status_code == 409
    assert repeat.json()["code"] == 2002


def test_human_review_approve_and_deliver_flow():
    with make_client(HUMAN_RESPONSES) as client:
        task_id = create_task(client)

        waiting = client.post(f"{API}/{task_id}/execute")
        assert waiting.status_code == 200
        assert waiting.json()["data"]["status"] == "HUMAN_REVIEW"

        approved = client.post(
            f"{API}/{task_id}/human-review",
            json={"decision": "APPROVE", "comments": "人工确认通过"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "PENDING_REVIEW"

        delivery = client.get(f"{API}/{task_id}/delivery")
        assert delivery.status_code == 200
        package = delivery.json()["data"]
        assert package["article_version"] == 2
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

        response = client.post(
            f"{API}/{task_id}/human-review",
            json={"decision": "REQUEST_EDIT"},
        )

        assert response.status_code == 400
        assert response.json()["code"] == 1001


def test_human_review_rejects_wrong_status(exec_client):
    task_id = create_task(exec_client)

    response = exec_client.post(
        f"{API}/{task_id}/human-review", json={"decision": "APPROVE"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == 2002


def test_pause_and_resume_endpoints(exec_client):
    task_id = create_task(exec_client)

    paused = exec_client.post(f"{API}/{task_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["data"]["paused"] is True

    blocked = exec_client.post(f"{API}/{task_id}/execute")
    assert blocked.status_code == 409

    resumed = exec_client.post(f"{API}/{task_id}/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["data"]["paused"] is False
    assert resumed.json()["data"]["status"] == "PENDING_REVIEW"


def test_delivery_decline_keeps_pending_review(exec_client):
    task_id = create_task(exec_client)
    exec_client.post(f"{API}/{task_id}/execute")

    response = exec_client.post(
        f"{API}/{task_id}/delivery/confirm", json={"confirmed": False}
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "PENDING_REVIEW"
    assert response.json()["data"]["delivery"] is not None


def test_delivery_confirm_requires_pending_review(exec_client):
    task_id = create_task(exec_client)

    response = exec_client.post(
        f"{API}/{task_id}/delivery/confirm", json={"confirmed": True}
    )

    assert response.status_code == 409
    assert response.json()["code"] == 2002


def test_events_list_returns_execution_logs(exec_client):
    task_id = create_task(exec_client)
    exec_client.post(f"{API}/{task_id}/execute")

    response = exec_client.get(f"{API}/{task_id}/events")

    assert response.status_code == 200
    events = response.json()["data"]
    assert len(events) == 7
    assert events[0]["agent_name"] == "chief_editor"
    assert events[-1]["agent_name"] == "delivery_preparer"
    assert all(event["finished_at"] for event in events)


def test_events_for_missing_task_returns_404(exec_client):
    response = exec_client.get(f"{API}/TASK_MISSING/events")

    assert response.status_code == 404
    assert response.json()["code"] == 2001
