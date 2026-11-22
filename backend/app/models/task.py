from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.graph.state import NewsTaskState


class TaskRecord(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revision_round: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    interface_retry_counts: Mapped[dict[str, int]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    execution_lock: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    @classmethod
    def from_state(cls, state: NewsTaskState) -> "TaskRecord":
        return cls(
            task_id=state.task_id,
            topic=state.topic,
            description=state.description,
            status=state.task_status.value,
            stage=state.current_stage.value,
            paused=False,
            revision_round=state.retry_count,
            interface_retry_counts={},
            state_json=state.model_dump(mode="json"),
            error_json=state.error.model_dump(mode="json") if state.error else None,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )

    def apply_state(self, state: NewsTaskState) -> None:
        self.topic = state.topic
        self.description = state.description
        self.status = state.task_status.value
        self.stage = state.current_stage.value
        self.revision_round = state.retry_count
        self.state_json = state.model_dump(mode="json")
        self.error_json = state.error.model_dump(mode="json") if state.error else None
        self.updated_at = state.updated_at

    def to_state(self) -> NewsTaskState:
        return NewsTaskState.model_validate(self.state_json)
