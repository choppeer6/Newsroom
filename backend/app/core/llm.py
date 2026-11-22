"""OpenAI-compatible chat completion client with JSON output support."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.retries import LLM_INTERFACE, consume_retry

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_MAX_ATTEMPTS = 2


class LLMError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class LLMClient(Protocol):
    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> dict[str, Any]: ...


def parse_json_object(content: str) -> dict[str, Any]:
    text = _JSON_FENCE.sub("", content.strip())
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError("LLM_INVALID_JSON", "模型未返回合法 JSON", retryable=True) from exc
    if not isinstance(parsed, dict):
        raise LLMError("LLM_INVALID_JSON", "模型返回的 JSON 不是对象", retryable=True)
    return parsed


class OpenAICompatibleClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return self._settings.llm_api_key is not None

    def _endpoint(self) -> str:
        return f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        if self._settings.llm_api_key is None:
            raise LLMError("LLM_NOT_CONFIGURED", "尚未配置 LLM_API_KEY")

        payload = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

        last_error: LLMError | None = None
        # trust_env=False keeps a malformed local HTTP_PROXY from breaking API calls.
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            trust_env=False,
        ) as client:
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    response = await client.post(
                        self._endpoint(), json=payload, headers=headers
                    )
                except httpx.HTTPError as exc:
                    last_error = LLMError(
                        "LLM_REQUEST_FAILED",
                        f"LLM 请求失败：{type(exc).__name__}",
                        retryable=True,
                    )
                    if attempt + 1 < _MAX_ATTEMPTS:
                        if not consume_retry(LLM_INTERFACE):
                            raise LLMError(
                                "INTERFACE_RETRY_EXCEEDED",
                                f"LLM 接口失败重试已达上限：{last_error.message}",
                            ) from exc
                        continue
                    raise last_error from exc

                if response.status_code >= 400:
                    last_error = LLMError(
                        "LLM_REQUEST_FAILED",
                        f"LLM 返回 HTTP {response.status_code}",
                        retryable=response.status_code == 429
                        or response.status_code >= 500,
                    )
                    if last_error.retryable and attempt + 1 < _MAX_ATTEMPTS:
                        if not consume_retry(LLM_INTERFACE):
                            raise LLMError(
                                "INTERFACE_RETRY_EXCEEDED",
                                f"LLM 接口失败重试已达上限：{last_error.message}",
                            )
                        continue
                    raise last_error

                try:
                    body = response.json()
                    content = body["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise LLMError(
                        "LLM_INVALID_RESPONSE", "LLM 响应结构不完整"
                    ) from exc

                if not isinstance(content, str) or not content.strip():
                    raise LLMError("LLM_INVALID_RESPONSE", "LLM 返回内容为空")
                return parse_json_object(content)

        raise last_error or LLMError("LLM_REQUEST_FAILED", "LLM 请求失败")
