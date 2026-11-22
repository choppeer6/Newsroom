import asyncio

from fastapi.testclient import TestClient

from app.db.session import dispose_db, init_db
from app.db.task_store import SqlTaskStore
from app.main import create_app
from app.schemas.domain import ExecutionLogEntry, TaskRequirements
from app.schemas.enums import (
    AgentName,
    AgentStatus,
    TaskStatus,
    WorkflowStage,
)
from app.services.task_service import TaskService


def test_sql_store_persists_task_and_events(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'store.db'}"

    async def scenario():
        factory = await init_db(url)
        service = TaskService(SqlTaskStore(factory))
        state = await service.create_task(
            topic="数据库持久化",
            description="验证任务与执行事件落库",
            requirements=TaskRequirements(),
        )
        state.task_status = TaskStatus.PLANNING
        state.current_stage = WorkflowStage.CHIEF_PLANNING
        state.execution_logs.append(
            ExecutionLogEntry(
                log_id="LOG_0001",
                task_id=state.task_id,
                agent_name=AgentName.CHIEF_EDITOR,
                status=AgentStatus.COMPLETED,
                output_summary="采编计划已生成",
            )
        )
        await service.save_state(state)
        await dispose_db()

        factory = await init_db(url)
        store = SqlTaskStore(factory)
        loaded = await store.get(state.task_id)
        events = await store.list_events(state.task_id)
        await dispose_db()
        return state.task_id, loaded, events

    task_id, loaded, events = asyncio.run(scenario())

    assert loaded is not None
    assert loaded.task_id == task_id
    assert loaded.task_status == TaskStatus.PLANNING
    assert loaded.current_stage == WorkflowStage.CHIEF_PLANNING
    assert [event.log_id for event in events] == ["LOG_0001"]
    assert events[0].output_summary == "采编计划已生成"


def test_sql_store_execution_lock_is_exclusive(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'lock.db'}"

    async def scenario():
        factory = await init_db(url)
        service = TaskService(SqlTaskStore(factory))
        state = await service.create_task(
            topic="执行锁",
            description="验证同一任务不能重复启动",
            requirements=TaskRequirements(),
        )
        first = await service.try_acquire_lock(state.task_id, "token-a")
        second = await service.try_acquire_lock(state.task_id, "token-b")
        await service.release_lock(state.task_id, "token-a")
        third = await service.try_acquire_lock(state.task_id, "token-b")
        await dispose_db()
        return first, second, third

    assert asyncio.run(scenario()) == (True, False, True)


def test_api_uses_database_store(db_client):
    created = db_client.post(
        "/api/news/tasks",
        json={"topic": "数据库接口", "description": "验证 API 落库"},
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["data"]["task_id"]

    detail = db_client.get(f"/api/news/tasks/{task_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["task_id"] == task_id


def test_task_survives_app_restart(db_settings):
    with TestClient(create_app(settings=db_settings)) as client:
        created = client.post(
            "/api/news/tasks",
            json={"topic": "重启后仍可查询", "description": "验证数据库持久化"},
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["data"]["task_id"]

    with TestClient(create_app(settings=db_settings)) as client:
        detail = client.get(f"/api/news/tasks/{task_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["task_id"] == task_id
        assert detail.json()["data"]["status"] == "CREATED"
