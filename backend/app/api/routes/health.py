from fastapi import APIRouter, Request

from app.api.response import ok
from app.schemas.api import ApiResponse, HealthData

router = APIRouter(tags=["system"])


@router.get("/health", response_model=ApiResponse[HealthData])
async def health(request: Request) -> ApiResponse[HealthData]:
    settings = request.app.state.settings
    return ok(
        request,
        HealthData(
            status="ok",
            version=settings.app_version,
            environment=settings.environment,
            llm_configured=settings.llm_api_key is not None,
            search_configured=settings.search_api_key is not None,
        ),
    )
