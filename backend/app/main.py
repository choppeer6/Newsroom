import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.response import get_request_id
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.services.task_service import TaskService
from app.services.task_store import InMemoryTaskStore

logger = logging.getLogger(__name__)


def _new_request_id(raw: str | None) -> str:
    candidate = (raw or "").strip()
    if candidate and len(candidate) <= 128 and all(
        char.isalnum() or char in "-_." for char in candidate
    ):
        return candidate
    return f"req_{uuid4().hex}"


def _error_response(
    request: Request,
    *,
    code: int,
    message: str,
    http_status: int,
    data: object | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={
            "code": code,
            "message": message,
            "data": data,
            "request_id": get_request_id(request),
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)

    app.state.settings = settings
    app.state.task_service = TaskService(InMemoryTaskStore())

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = _new_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request,
            code=exc.code,
            message=exc.message,
            http_status=exc.http_status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "loc": list(error.get("loc", [])),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        return _error_response(
            request,
            code=1001,
            message="参数校验失败",
            http_status=400,
            data={"errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == 404:
            return _error_response(
                request, code=2001, message="资源不存在", http_status=404
            )
        return _error_response(
            request,
            code=1001,
            message=str(exc.detail),
            http_status=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return _error_response(
            request,
            code=5000,
            message="服务内部错误",
            http_status=500,
        )

    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
