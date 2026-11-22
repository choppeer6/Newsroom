"""Conditional edge functions for the newsroom workflow."""

from __future__ import annotations

from app.graph.state import NewsTaskState
from app.schemas.enums import ChiefDecision, HumanDecision, TaskStatus

END = "end"


def _failed(state: NewsTaskState) -> bool:
    return state.task_status == TaskStatus.FAILED


def route_after_planning(state: NewsTaskState) -> str:
    return END if _failed(state) else "reporter"


def route_after_reporter(state: NewsTaskState) -> str:
    return END if _failed(state) else "editor"


def route_after_editor(state: NewsTaskState) -> str:
    return END if _failed(state) else "fact_checker"


def route_after_fact_checker(state: NewsTaskState) -> str:
    return END if _failed(state) else "special_check"


def route_after_special_check(state: NewsTaskState) -> str:
    return END if _failed(state) else "chief_review"


def route_after_review(state: NewsTaskState) -> str:
    if _failed(state):
        return END
    decision = state.chief_decision
    if decision == ChiefDecision.APPROVE:
        return "prepare_delivery"
    if decision == ChiefDecision.REQUEST_EDIT:
        return "editor"
    if decision == ChiefDecision.REQUEST_RESEARCH:
        return "reporter"
    if decision == ChiefDecision.HUMAN_REVIEW:
        return "human_approval"
    return END


def route_after_human_approval(state: NewsTaskState) -> str:
    if _failed(state):
        return END
    decision = state.human_decision
    if decision == HumanDecision.APPROVE:
        return (
            "prepare_delivery"
            if state.task_status == TaskStatus.RUNNING
            else END
        )
    if decision == HumanDecision.REQUEST_EDIT:
        return "editor"
    if decision == HumanDecision.REQUEST_RESEARCH:
        return "reporter"
    return END
