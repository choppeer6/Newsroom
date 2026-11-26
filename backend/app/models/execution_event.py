from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.schemas.domain import ExecutionLogEntry


class ExecutionEventRecord(Base):
    __tablename__ = "execution_events"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_event_task_seq"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    agent: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @classmethod
    def from_log(
        cls, task_id: str, seq: int, entry: ExecutionLogEntry
    ) -> "ExecutionEventRecord":
        return cls(
            event_id=entry.log_id,
            task_id=task_id,
            seq=seq,
            agent=entry.agent_name.value,
            status=entry.status.value,
            input_summary=entry.input_summary,
            output_summary=entry.output_summary,
            error_message=entry.error_message,
            started_at=entry.started_at,
            finished_at=entry.finished_at,
        )

    def to_log(self) -> ExecutionLogEntry:
        return ExecutionLogEntry(
            log_id=self.event_id,
            task_id=self.task_id,
            agent_name=self.agent,
            status=self.status,
            input_summary=self.input_summary,
            output_summary=self.output_summary,
            error_message=self.error_message,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )
