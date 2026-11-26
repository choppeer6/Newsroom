"""Per-task accounting of external interface retries.

Retries are tracked separately from article revision rounds: a retry budget
limits how often a failing LLM or search call may be attempted again, while
``revision_round`` counts editorial revisions.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field

LLM_INTERFACE = "llm"
SEARCH_INTERFACE = "search"


@dataclass
class InterfaceRetryTracker:
    limit: int
    counts: dict[str, int] = field(default_factory=dict)

    def consume(self, interface: str) -> bool:
        used = self.counts.get(interface, 0)
        if used >= self.limit:
            return False
        self.counts[interface] = used + 1
        return True

    def remaining(self, interface: str) -> int:
        return max(self.limit - self.counts.get(interface, 0), 0)

    def snapshot(self) -> dict[str, int]:
        return dict(self.counts)


_tracker: ContextVar[InterfaceRetryTracker | None] = ContextVar(
    "interface_retry_tracker", default=None
)


def set_tracker(tracker: InterfaceRetryTracker) -> Token:
    return _tracker.set(tracker)


def reset_tracker(token: Token) -> None:
    _tracker.reset(token)


def current_tracker() -> InterfaceRetryTracker | None:
    return _tracker.get()


def consume_retry(interface: str) -> bool:
    """Spend one retry for ``interface``; False when the task budget is used up."""
    tracker = _tracker.get()
    if tracker is None:
        return True
    return tracker.consume(interface)
