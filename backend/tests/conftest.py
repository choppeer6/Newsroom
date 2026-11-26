import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.task_store import InMemoryTaskStore


@pytest.fixture()
def app():
    return create_app(task_store=InMemoryTaskStore())


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_settings(tmp_path):
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'newsroom-test.db'}",
        database_echo=False,
    )


@pytest.fixture()
def db_client(db_settings):
    with TestClient(create_app(settings=db_settings)) as test_client:
        yield test_client
