import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.core.llm import LLMError, OpenAICompatibleClient
from app.core.retries import InterfaceRetryTracker, reset_tracker, set_tracker


def make_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "llm_base_url": "https://llm.example/v1",
        "llm_api_key": "sk-test",
        "llm_model": "test-model",
    }
    values.update(overrides)
    return Settings(**values)


def test_complete_json_parses_fenced_json_and_sends_json_mode():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '```json\n{"ok": true}\n```'}}
                ]
            },
        )

    client = OpenAICompatibleClient(
        make_settings(), transport=httpx.MockTransport(handler)
    )

    result = asyncio.run(client.complete_json(system="system", user="user"))

    assert result == {"ok": True}
    body = json.loads(requests[0].content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "test-model"
    assert requests[0].headers["authorization"] == "Bearer sk-test"


def test_complete_json_does_not_retry_auth_error():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": "bad key"})

    client = OpenAICompatibleClient(
        make_settings(), transport=httpx.MockTransport(handler)
    )

    with pytest.raises(LLMError) as exc_info:
        asyncio.run(client.complete_json(system="system", user="user"))

    assert exc_info.value.code == "LLM_REQUEST_FAILED"
    assert exc_info.value.retryable is False
    assert calls == 1


def test_complete_json_retries_server_error_once():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )

    client = OpenAICompatibleClient(
        make_settings(), transport=httpx.MockTransport(handler)
    )

    result = asyncio.run(client.complete_json(system="system", user="user"))

    assert result == {"ok": True}
    assert calls == 2


def test_complete_json_rejects_non_json_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "not json"}}]}
        )

    client = OpenAICompatibleClient(
        make_settings(), transport=httpx.MockTransport(handler)
    )

    with pytest.raises(LLMError) as exc_info:
        asyncio.run(client.complete_json(system="system", user="user"))

    assert exc_info.value.code == "LLM_INVALID_JSON"
    assert exc_info.value.retryable is True


def test_complete_json_rejects_incomplete_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    client = OpenAICompatibleClient(
        make_settings(), transport=httpx.MockTransport(handler)
    )

    with pytest.raises(LLMError) as exc_info:
        asyncio.run(client.complete_json(system="system", user="user"))

    assert exc_info.value.code == "LLM_INVALID_RESPONSE"


def test_complete_json_requires_api_key():
    client = OpenAICompatibleClient(make_settings(llm_api_key=""))

    with pytest.raises(LLMError) as exc_info:
        asyncio.run(client.complete_json(system="system", user="user"))

    assert exc_info.value.code == "LLM_NOT_CONFIGURED"
    assert exc_info.value.retryable is False


def test_retry_budget_records_consumed_retries():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )

    client = OpenAICompatibleClient(
        make_settings(), transport=httpx.MockTransport(handler)
    )
    tracker = InterfaceRetryTracker(limit=2)
    token = set_tracker(tracker)
    try:
        result = asyncio.run(client.complete_json(system="system", user="user"))
    finally:
        reset_tracker(token)

    assert result == {"ok": True}
    assert calls == 2
    assert tracker.snapshot() == {"llm": 1}


def test_retry_budget_blocks_retry_when_exhausted():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": "down"})

    client = OpenAICompatibleClient(
        make_settings(), transport=httpx.MockTransport(handler)
    )
    tracker = InterfaceRetryTracker(limit=2, counts={"llm": 2})
    token = set_tracker(tracker)
    try:
        with pytest.raises(LLMError) as exc_info:
            asyncio.run(client.complete_json(system="system", user="user"))
    finally:
        reset_tracker(token)

    assert exc_info.value.code == "INTERFACE_RETRY_EXCEEDED"
    assert exc_info.value.retryable is False
    assert calls == 1
    assert tracker.snapshot() == {"llm": 2}
