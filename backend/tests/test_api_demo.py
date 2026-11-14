import time

import pytest

from app.graph.nodes import create_default_agents
from app.graph.workflow import NewsroomWorkflow
from app.services.demo_service import DemoService
from app.services.publish_service import MockPublishService
from tests.fakes import FakeLLM, FakeSearch, make_hit, make_requirements

API = "/api/news/demo"

PLAN = {
    "topic_analysis": "选题分析内容不少于三十个字的说明文本，用于验证联调页面。",
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
EDIT_REVISED = {**EDIT, "structure_changes": "按退回意见合并段落"}
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
HUMAN_REVIEW = {
    "chief_decision": "HUMAN_REVIEW",
    "review_comments": "核心事实存在争议，需要人工判断。",
}


@pytest.fixture()
def install_demo(app):
    def install(responses=None) -> FakeLLM:
        llm = FakeLLM(responses or [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, APPROVE])
        agents = create_default_agents(
            llm=llm,
            search=FakeSearch(default=[make_hit()]),
            publish_service=MockPublishService(),
        )
        app.state.demo_service = DemoService(
            workflow=NewsroomWorkflow(agents=agents, max_retry=2)
        )
        return llm

    return install


def wait_for(client, task_id: str, phase: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    snapshot = None
    while time.time() < deadline:
        response = client.get(f"{API}/tasks/{task_id}")
        assert response.status_code == 200, response.text
        snapshot = response.json()["data"]
        if snapshot["phase"] == phase:
            return snapshot
        if snapshot["phase"] == "failed" and phase != "failed":
            raise AssertionError(f"workflow failed: {snapshot['error']}")
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {phase}: {snapshot}")


def start(client) -> str:
    response = client.post(
        f"{API}/tasks",
        json={
            "topic": "人工智能在高校教育中的应用",
            "description": "关注教学实践",
            "requirements": make_requirements().model_dump(),
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]["task_id"]


def test_demo_page_is_served(client):
    response = client.get("/demo")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "工作流联调台" in response.text


def test_demo_meta_reports_configuration(client):
    response = client.get(f"{API}/meta")

    assert response.status_code == 200
    data = response.json()["data"]
    assert isinstance(data["llm_configured"], bool)
    assert isinstance(data["search_configured"], bool)
    assert data["max_revision_rounds"] == 2


def test_demo_happy_path_reaches_publish_confirmation(client, install_demo):
    install_demo()
    task_id = start(client)

    snapshot = wait_for(client, task_id, "publish_confirmation")

    assert snapshot["task_id"] == task_id
    assert snapshot["article"]["title"] == DRAFT["title"]
    assert snapshot["article"]["version"] == 2
    assert snapshot["fact_check"]["overall_result"] == "PASSED"
    assert snapshot["chief"]["decision"] == "APPROVE"
    assert [item["agent"] for item in snapshot["logs"]] == [
        "chief_editor",
        "reporter",
        "editor",
        "fact_checker",
        "chief_editor",
        "publisher",
    ]

    response = client.post(f"{API}/tasks/{task_id}/confirm", json={"confirm": True})
    assert response.status_code == 200, response.text
    final = wait_for(client, task_id, "finished")

    assert final["task_status"] == "PUBLISHED"
    assert final["publication"]["status"] == "PUBLISHED"
    assert final["publication"]["external_url"].startswith("https://newsroom.local/")


def test_demo_human_review_can_request_edit(client, install_demo):
    install_demo(
        [
            PLAN,
            QUERIES,
            DRAFT,
            EDIT,
            EXTRACT,
            VERIFY,
            HUMAN_REVIEW,
            EDIT_REVISED,
            EXTRACT,
            VERIFY,
            APPROVE,
        ]
    )
    task_id = start(client)

    snapshot = wait_for(client, task_id, "human_review")
    assert snapshot["chief"]["decision"] == "HUMAN_REVIEW"

    response = client.post(
        f"{API}/tasks/{task_id}/review",
        json={
            "decision": "REQUEST_EDIT",
            "comments": "同意主编意见，先调整结构。",
            "revision_reason": "结构松散",
            "revision_requirements": ["合并重复段落"],
        },
    )
    assert response.status_code == 200, response.text

    updated = wait_for(client, task_id, "publish_confirmation")
    assert updated["retry_count"] == 1
    assert updated["article"]["version"] == 3
    assert updated["fact_check"]["article_version"] == 3


def test_demo_review_requires_revision_fields(client, install_demo):
    install_demo(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, HUMAN_REVIEW]
    )
    task_id = start(client)
    wait_for(client, task_id, "human_review")

    response = client.post(f"{API}/tasks/{task_id}/review", json={"decision": "REQUEST_EDIT"})

    assert response.status_code == 400
    assert response.json()["code"] == 1001


def test_demo_rejects_review_during_confirmation(client, install_demo):
    install_demo()
    task_id = start(client)
    wait_for(client, task_id, "publish_confirmation")

    response = client.post(
        f"{API}/tasks/{task_id}/review",
        json={"decision": "APPROVE"},
    )

    assert response.status_code == 409
    assert "发布确认" in response.json()["message"]


def test_demo_confirm_requires_pending_publication(client, install_demo):
    install_demo(
        [PLAN, QUERIES, DRAFT, EDIT, EXTRACT, VERIFY, HUMAN_REVIEW]
    )
    task_id = start(client)
    wait_for(client, task_id, "human_review")

    response = client.post(f"{API}/tasks/{task_id}/confirm", json={"confirm": True})

    assert response.status_code == 409
    assert "发布确认" in response.json()["message"]


def test_demo_task_not_found(client):
    response = client.get(f"{API}/tasks/DEMO_MISSING")

    assert response.status_code == 404
    assert response.json()["code"] == 2001
