import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.response import get_request_id
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import dispose_db, init_db
from app.db.task_store import SqlTaskStore
from app.graph.workflow import NewsroomWorkflow
from app.services.demo_service import DemoService
from app.services.execution_service import ExecutionService
from app.services.task_service import TaskService
from app.services.task_store import TaskStore

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"


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


def create_app(
    *,
    settings: Settings | None = None,
    task_store: TaskStore | None = None,
    workflow: NewsroomWorkflow | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if task_store is not None:
            application.state.task_service = TaskService(task_store)
        else:
            session_factory = await init_db(
                resolved_settings.database_url,
                echo=resolved_settings.database_echo,
            )
            application.state.task_service = TaskService(
                SqlTaskStore(session_factory)
            )
        application.state.execution_service = ExecutionService(
            application.state.task_service,
            workflow=workflow,
        )
        recovered = await application.state.execution_service.recover_stale_tasks()
        if recovered:
            logger.warning("marked %d orphaned RUNNING tasks as FAILED", recovered)
        try:
            yield
        finally:
            if task_store is None:
                await dispose_db()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )

    app.state.settings = resolved_settings
    app.state.demo_service = DemoService()

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = _new_request_id(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
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

    app.include_router(api_router, prefix=resolved_settings.api_prefix)

    @app.get("/demo", include_in_schema=False)
    async def demo_console() -> FileResponse:
        return FileResponse(WEB_DIR / "demo.html")

    return app


app = create_app()
