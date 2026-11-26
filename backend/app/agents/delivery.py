"""Deterministic pre-delivery preparation stub for the D module handoff."""

from app.agents.base import BaseAgent
from app.agents.contracts import (
    DeliveryPreparationInput,
    DeliveryPreparationOutput,
)
from app.core.utils import generate_id
from app.schemas.domain import DeliveryPackage
from app.schemas.enums import AgentName


class DeliveryPreparationAgent(
    BaseAgent[DeliveryPreparationInput, DeliveryPreparationOutput]
):
    name = AgentName.DELIVERY_PREPARER

    async def run(
        self, payload: DeliveryPreparationInput
    ) -> DeliveryPreparationOutput:
        package = DeliveryPackage(
            package_id=generate_id("DLV"),
            task_id=payload.task_id,
            article_id=payload.article_id,
            article_version=payload.article_version,
            fact_check_report_id=payload.fact_check_report.report_id,
            special_check_report_id=payload.special_check_report.report_id,
            source_ids=[source.source_id for source in payload.sources],
            note="预发布材料已准备，等待用户复核与导出。",
        )
        return DeliveryPreparationOutput(package=package)
