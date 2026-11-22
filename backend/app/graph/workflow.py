"""LangGraph assembly and a thin runtime wrapper around the compiled graph."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.core.config import get_settings
from app.graph import routing
from app.graph.nodes import WorkflowAgents, create_default_agents, make_nodes
from app.graph.state import NewsTaskState
from app.schemas import domain as domain_schemas
from app.schemas import enums as enum_schemas

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 50


def _msgpack_allowlist() -> list[tuple[str, str]]:
    allowlist: list[tuple[str, str]] = []
    for module in (domain_schemas, enum_schemas):
        for name, value in vars(module).items():
            if isinstance(value, type) and value.__module__ == module.__name__:
                allowlist.append((module.__name__, name))
    return allowlist


def default_checkpointer() -> MemorySaver:
    return MemorySaver(
        serde=JsonPlusSerializer(allowed_msgpack_modules=_msgpack_allowlist())
    )


def build_workflow(
    *,
    agents: WorkflowAgents | None = None,
    checkpointer: MemorySaver | None = None,
    max_revision_rounds: int | None = None,
):
    revision_cap = (
        get_settings().max_revision_rounds
        if max_revision_rounds is None
        else max_revision_rounds
    )
    resolved_agents = agents or create_default_agents()
    nodes = make_nodes(resolved_agents, max_revision_rounds=revision_cap)

    builder = StateGraph(NewsTaskState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "chief_planning")
    builder.add_conditional_edges(
        "chief_planning",
        routing.route_after_planning,
        {"reporter": "reporter", routing.END: END},
    )
    builder.add_conditional_edges(
        "reporter",
        routing.route_after_reporter,
        {"editor": "editor", routing.END: END},
    )
    builder.add_conditional_edges(
        "editor",
        routing.route_after_editor,
        {"fact_checker": "fact_checker", routing.END: END},
    )
    builder.add_conditional_edges(
        "fact_checker",
        routing.route_after_fact_checker,
        {"special_check": "special_check", routing.END: END},
    )
    builder.add_conditional_edges(
        "special_check",
        routing.route_after_special_check,
        {"chief_review": "chief_review", routing.END: END},
    )
    builder.add_conditional_edges(
        "chief_review",
        routing.route_after_review,
        {
            "prepare_delivery": "prepare_delivery",
            "editor": "editor",
            "reporter": "reporter",
            "human_approval": "human_approval",
            routing.END: END,
        },
    )
    builder.add_conditional_edges(
        "human_approval",
        routing.route_after_human_approval,
        {
            "prepare_delivery": "prepare_delivery",
            "editor": "editor",
            "reporter": "reporter",
            routing.END: END,
        },
    )
    builder.add_edge("prepare_delivery", END)

    return builder.compile(checkpointer=checkpointer or default_checkpointer())


@dataclass(frozen=True)
class WorkflowResult:
    state: NewsTaskState
    interrupt: dict[str, Any] | None = None


def _coerce_state(raw: Any) -> NewsTaskState:
    if isinstance(raw, NewsTaskState):
        return raw
    data = {key: value for key, value in raw.items() if key in NewsTaskState.model_fields}
    return NewsTaskState.model_validate(data)


def _interrupt_value(source: Any) -> dict[str, Any] | None:
    interrupts = source.get("__interrupt__") if isinstance(source, dict) else None
    if not interrupts:
        interrupts = getattr(source, "interrupts", None)
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {"value": value}


class NewsroomWorkflow:
    def __init__(
        self,
        *,
        agents: WorkflowAgents | None = None,
        checkpointer: MemorySaver | None = None,
        max_revision_rounds: int | None = None,
    ) -> None:
        self.max_revision_rounds = (
            get_settings().max_revision_rounds
            if max_revision_rounds is None
            else max_revision_rounds
        )
        self._graph = build_workflow(
            agents=agents,
            checkpointer=checkpointer,
            max_revision_rounds=self.max_revision_rounds,
        )

    @property
    def graph(self):
        return self._graph

    def _config(self, task_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": task_id},
            "recursion_limit": RECURSION_LIMIT,
        }

    async def run(self, state: NewsTaskState) -> WorkflowResult:
        raw = await self._graph.ainvoke(state, self._config(state.task_id))
        return WorkflowResult(state=_coerce_state(raw), interrupt=_interrupt_value(raw))

    async def resume(self, task_id: str, value: Any) -> WorkflowResult:
        raw = await self._graph.ainvoke(Command(resume=value), self._config(task_id))
        return WorkflowResult(state=_coerce_state(raw), interrupt=_interrupt_value(raw))

    async def get_state(self, task_id: str) -> WorkflowResult | None:
        snapshot = await self._graph.aget_state(self._config(task_id))
        if not snapshot or not snapshot.values:
            return None
        return WorkflowResult(
            state=_coerce_state(snapshot.values),
            interrupt=_interrupt_value(snapshot),
        )
