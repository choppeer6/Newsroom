import asyncio

from app.core.retries import consume_retry
from app.graph.state import NewsTaskState
from app.graph.workflow import _tracked_node
from app.schemas.api import TaskDetail


def make_state(**overrides) -> NewsTaskState:
    values = {"task_id": "TASK_RETRY", "topic": "选题"}
    values.update(overrides)
    return NewsTaskState(**values)


def test_tracked_node_persists_consumed_retries():
    state = make_state()

    async def node(current: NewsTaskState) -> dict:
        assert consume_retry("llm") is True
        assert consume_retry("llm") is False
        assert consume_retry("search") is True
        return {"revision_round": 0}

    result = asyncio.run(_tracked_node(node, 1)(state))

    assert result["interface_retry_counts"] == {"llm": 1, "search": 1}
    detail = TaskDetail.from_state(state.model_copy(update=result))
    assert detail.interface_retry_counts == {"llm": 1, "search": 1}
    assert detail.revision_round == 0


def test_tracked_node_keeps_existing_counts_without_new_retries():
    state = make_state(interface_retry_counts={"llm": 1})

    async def node(current: NewsTaskState) -> dict:
        return {"revision_round": 0}

    result = asyncio.run(_tracked_node(node, 2)(state))

    assert "interface_retry_counts" not in result


def test_tracked_node_accumulates_seeded_counts():
    state = make_state(interface_retry_counts={"llm": 1})

    async def node(current: NewsTaskState) -> dict:
        assert consume_retry("llm") is True
        assert consume_retry("llm") is False
        return {}

    result = asyncio.run(_tracked_node(node, 2)(state))

    assert result["interface_retry_counts"] == {"llm": 2}
