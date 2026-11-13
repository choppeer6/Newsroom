from __future__ import annotations

import logging

from app.agents.base import BaseAgent
from app.agents.contracts import PublisherInput, PublisherOutput
from app.agents.runtime import failure
from app.core.utils import generate_id
from app.schemas.domain import ErrorInfo, Publication
from app.schemas.enums import (
    AgentName,
    AgentStatus,
    ChiefDecision,
    FactCheckOverallResult,
    PublicationStatus,
)
from app.services.publish_service import (
    MockPublishService,
    PublishError,
    PublishService,
)

logger = logging.getLogger(__name__)


class PublisherAgent(BaseAgent[PublisherInput, PublisherOutput]):
    name = AgentName.PUBLISHER

    def __init__(self, *, publish_service: PublishService | None = None) -> None:
        self._service = publish_service or MockPublishService()

    async def run(self, payload: PublisherInput) -> PublisherOutput:
        logger.info(
            "publisher start task_id=%s confirmed=%s",
            payload.task_id,
            payload.user_confirmation,
        )
        if payload.chief_decision != ChiefDecision.APPROVE:
            return failure(
                PublisherOutput,
                "PUBLISH_NOT_APPROVED",
                "主编尚未批准该稿件，不能进入发布流程",
            )
        if payload.fact_check_status == FactCheckOverallResult.FAILED:
            return failure(
                PublisherOutput,
                "PUBLISH_FACT_CHECK_FAILED",
                "事实核查未通过，不能进入发布流程",
            )

        if not payload.user_confirmation:
            publication = Publication(
                publication_id=generate_id("PUB"),
                article_id=payload.article_id,
                article_version=payload.article_version,
                status=PublicationStatus.PENDING_PUBLISH,
                message="稿件已进入待发布状态，等待用户确认",
            )
            logger.info(
                "publisher pending task_id=%s version=%d",
                payload.task_id,
                payload.article_version,
            )
            return PublisherOutput(publication=publication)

        try:
            publication = await self._service.publish(
                article_id=payload.article_id,
                article_version=payload.article_version,
            )
        except PublishError as exc:
            logger.warning(
                "publisher failed task_id=%s code=PUBLISH_FAILED", payload.task_id
            )
            return PublisherOutput(
                status=AgentStatus.FAILED,
                error=ErrorInfo(
                    code="PUBLISH_FAILED",
                    message=exc.message,
                    retryable=exc.retryable,
                ),
                publication=Publication(
                    publication_id=generate_id("PUB"),
                    article_id=payload.article_id,
                    article_version=payload.article_version,
                    status=PublicationStatus.PENDING_PUBLISH,
                    message=f"发布失败：{exc.message}",
                ),
            )

        logger.info(
            "publisher completed task_id=%s publication=%s",
            payload.task_id,
            publication.publication_id,
        )
        return PublisherOutput(publication=publication)
