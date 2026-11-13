import asyncio

from app.schemas.domain import TaskRequirements
from app.schemas.enums import TaskStatus, WorkflowStage
from app.services.task_service import TaskService
from app.services.task_store import InMemoryTaskStore

SAMPLE_TASK = {
    "topic": "人工智能技术在高校教育中的应用",
    "description": "关注人工智能在高校教学中的应用现状",
    "requirements": {
        "style": "客观新闻报道",
        "target_length": 1500,
        "focus": ["应用案例", "实际效果", "存在的问题"],
    },
}


def create_task(
    client,
    topic: str = SAMPLE_TASK["topic"],
    description: str = SAMPLE_TASK["description"],
) -> dict:
    payload = {**SAMPLE_TASK, "topic": topic, "description": description}
    response = client.post("/api/news/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_health(client):
    response = client.get("/api/news/health")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["status"] == "ok"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_create_and_get_task(client):
    created = create_task(client)

    assert created["task_id"].startswith("TASK_")
    assert created["status"] == "CREATED"
    assert created["created_at"]

    response = client.get(f"/api/news/tasks/{created['task_id']}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["task_id"] == created["task_id"]
    assert data["status"] == "CREATED"
    assert data["current_stage"] == "created"
    assert data["description"] == SAMPLE_TASK["description"]
    assert data["requirements"]["focus"] == SAMPLE_TASK["requirements"]["focus"]
    assert data["retry_count"] == 0
    assert data["latest_fact_check"] is None
    assert data["publication_status"] is None
    assert data["error"] is None


def test_create_task_with_default_requirements(client):
    response = client.post("/api/news/tasks", json={"topic": "默认配置选题"})

    assert response.status_code == 201
    task_id = response.json()["data"]["task_id"]
    detail = client.get(f"/api/news/tasks/{task_id}").json()["data"]
    assert detail["requirements"]["style"] == "客观新闻报道"
    assert detail["requirements"]["target_length"] == 1500
    assert detail["requirements"]["focus"] == []


def test_create_task_validation_error(client):
    response = client.post("/api/news/tasks", json={"topic": ""})

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 1001
    assert body["data"]["errors"]


def test_create_task_rejects_invalid_target_length(client):
    payload = {
        "topic": "长度校验",
        "requirements": {"style": "消息", "target_length": 100, "focus": []},
    }

    response = client.post("/api/news/tasks", json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == 1001


def test_create_task_rejects_unknown_field(client):
    payload = {"topic": "未知字段", "unexpected": "value"}

    response = client.post("/api/news/tasks", json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == 1001


def test_get_missing_task_returns_404(client):
    response = client.get("/api/news/tasks/TASK_MISSING")

    assert response.status_code == 404
    assert response.json()["code"] == 2001


def test_unknown_route_returns_error_envelope(client):
    response = client.get("/api/news/unknown")

    assert response.status_code == 404
    assert response.json()["code"] == 2001


def test_cancel_task_and_reject_repeat(client):
    created = create_task(client)
    task_id = created["task_id"]

    response = client.post(f"/api/news/tasks/{task_id}/cancel")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "CANCELLED"
    assert data["current_stage"] == "cancelled"

    repeat = client.post(f"/api/news/tasks/{task_id}/cancel")
    assert repeat.status_code == 409
    assert repeat.json()["code"] == 2002


def test_list_tasks_filter_and_pagination(client):
    create_task(client, "人工智能教育实践", "高校教学案例")
    create_task(client, "人工智能医疗应用", "医疗影像辅助诊断")
    create_task(client, "新能源汽车产业", "产业政策与市场数据")

    filtered = client.get("/api/news/tasks", params={"keyword": "人工智能"})
    assert filtered.status_code == 200
    filtered_data = filtered.json()["data"]
    assert filtered_data["total"] == 2
    assert len(filtered_data["items"]) == 2

    paged = client.get(
        "/api/news/tasks",
        params={"keyword": "人工智能", "page": 1, "page_size": 1},
    )
    paged_data = paged.json()["data"]
    assert paged_data["total"] == 2
    assert len(paged_data["items"]) == 1

    by_status = client.get("/api/news/tasks", params={"status": "CREATED"})
    assert by_status.json()["data"]["total"] == 3

    invalid_status = client.get("/api/news/tasks", params={"status": "UNKNOWN"})
    assert invalid_status.status_code == 400
    assert invalid_status.json()["code"] == 1001


def test_request_id_is_echoed(client):
    response = client.get(
        "/api/news/health",
        headers={"X-Request-ID": "req-test-123"},
    )

    assert response.headers["X-Request-ID"] == "req-test-123"
    assert response.json()["request_id"] == "req-test-123"


def test_service_generates_news_task_state():
    async def scenario():
        service = TaskService(InMemoryTaskStore())
        state = await service.create_task(
            topic="服务层状态生成",
            description="验证 State 初始字段",
            requirements=TaskRequirements(),
        )
        return state, await service.get_task(state.task_id)

    created, fetched = asyncio.run(scenario())

    assert created.task_id.startswith("TASK_")
    assert fetched.task_status == TaskStatus.CREATED
    assert fetched.current_stage == WorkflowStage.CREATED
    assert fetched.retry_count == 0
    assert fetched.requirements.target_length == 1500
