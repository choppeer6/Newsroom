from typing import TypeVar

from fastapi import Request

from app.schemas.api import ApiResponse

T = TypeVar("T")


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def ok(request: Request, data: T, *, message: str = "ok", code: int = 0) -> ApiResponse[T]:
    return ApiResponse(
        code=code,
        message=message,
        data=data,
        request_id=get_request_id(request),
    )
