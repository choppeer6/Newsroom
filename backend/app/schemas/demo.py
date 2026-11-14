"""Request models for the temporary workflow demo console."""

from pydantic import Field, model_validator

from app.schemas.base import StrictModel
from app.schemas.domain import TaskRequirements
from app.schemas.enums import HumanDecision

_REVISION_DECISIONS = {HumanDecision.REQUEST_EDIT, HumanDecision.REQUEST_RESEARCH}


class DemoStartRequest(StrictModel):
    topic: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    requirements: TaskRequirements = Field(default_factory=TaskRequirements)


class DemoReviewRequest(StrictModel):
    decision: HumanDecision
    comments: str | None = Field(default=None, max_length=2000)
    revision_reason: str | None = Field(default=None, max_length=1000)
    revision_requirements: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _revision_fields(self) -> "DemoReviewRequest":
        if self.decision in _REVISION_DECISIONS:
            if not (self.revision_reason or "").strip():
                raise ValueError("退回修改必须填写原因")
            if not [item for item in self.revision_requirements if item.strip()]:
                raise ValueError("退回修改至少需要一条修改要求")
        return self


class DemoConfirmRequest(StrictModel):
    confirm: bool
