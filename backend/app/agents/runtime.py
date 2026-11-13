"""Shared helpers for agent execution, validation retries and failure output."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from app.agents.contracts import AgentOutput
from app.core.llm import LLMClient, LLMError
from app.prompts.loader import PromptSpec
from app.schemas.domain import ErrorInfo
from app.schemas.enums import AgentStatus
from app.tools.search import SearchError, SearchNotConfiguredError

logger = logging.getLogger(__name__)

T = TypeVar("T")
OutputT = TypeVar("OutputT", bound=AgentOutput)


def dump_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in value
        ]
    return json.dumps(value, ensure_ascii=False, indent=2)


def describe_validation_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for error in exc.errors(include_url=False, include_input=False):
            location = ".".join(str(item) for item in error.get("loc", ()))
            message = str(error.get("msg", ""))
            parts.append(f"{location}: {message}" if location else message)
        return "; ".join(parts)[:1000]
    return str(exc)[:1000]


async def complete_validated(
    llm: LLMClient,
    spec: PromptSpec,
    *,
    context: dict[str, Any],
    validate: Callable[[dict[str, Any]], T],
    retries: int = 1,
) -> T:
    user = spec.render(**context)
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            data = await llm.complete_json(
                system=spec.system,
                user=user,
                temperature=spec.temperature,
                max_tokens=spec.max_tokens,
            )
        except LLMError as exc:
            if exc.code != "LLM_INVALID_JSON" or attempt >= retries:
                raise
            last_error = exc
            user = (
                f"{user}\n\n上一次输出不是合法 JSON。请只输出一个 JSON 对象，"
                "不要使用 Markdown 代码块或添加解释文字。"
            )
            continue

        try:
            return validate(data)
        except (ValidationError, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                raise LLMError(
                    "LLM_OUTPUT_INVALID",
                    f"模型输出未通过校验：{describe_validation_error(exc)}",
                ) from exc
            user = (
                f"{user}\n\n上一次输出未通过校验：{describe_validation_error(exc)}\n"
                "请严格按要求的 JSON 结构重新输出，不要添加任何额外字段。"
            )

    raise LLMError(
        "LLM_OUTPUT_INVALID",
        f"模型输出未通过校验：{describe_validation_error(last_error) if last_error else '未知错误'}",
    )


def failure(
    output_type: type[OutputT],
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> OutputT:
    return output_type(
        status=AgentStatus.FAILED,
        error=ErrorInfo(
            code=code,
            message=message,
            retryable=retryable,
            details=details,
        ),
    )


def failure_for(output_type: type[OutputT], exc: Exception) -> OutputT:
    if isinstance(exc, SearchNotConfiguredError):
        return failure(output_type, "SEARCH_NOT_CONFIGURED", exc.message)
    if isinstance(exc, SearchError):
        return failure(
            output_type, "SEARCH_FAILED", exc.message, retryable=exc.retryable
        )
    if isinstance(exc, LLMError):
        return failure(output_type, exc.code, exc.message, retryable=exc.retryable)
    if isinstance(exc, (ValidationError, ValueError)):
        reason = describe_validation_error(exc)
        return failure(
            output_type,
            "LLM_OUTPUT_INVALID",
            f"模型输出未通过校验：{reason}",
            details={"reason": reason},
        )
    logger.exception("agent internal error: %s", type(exc).__name__)
    return failure(output_type, "AGENT_INTERNAL_ERROR", "Agent 执行出现内部错误")
