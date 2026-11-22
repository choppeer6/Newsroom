"""Deterministic special-check stub for the D module handoff."""

from app.agents.base import BaseAgent
from app.agents.contracts import SpecialCheckInput, SpecialCheckOutput
from app.schemas.domain import SpecialCheckFinding
from app.schemas.enums import AgentName, SpecialCheckResult


class SpecialCheckAgent(BaseAgent[SpecialCheckInput, SpecialCheckOutput]):
    name = AgentName.SPECIAL_CHECKER

    async def run(self, payload: SpecialCheckInput) -> SpecialCheckOutput:
        return SpecialCheckOutput(
            finding=SpecialCheckFinding(
                result=SpecialCheckResult.PASSED,
                summary="专项检查桩：未发现内容规范或敏感信息问题。",
                issues=[],
            ),
            article_id=payload.article_id,
            article_version=payload.article_version,
        )
