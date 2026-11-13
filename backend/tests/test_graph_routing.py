from app.graph import routing
from app.graph.state import NewsTaskState
from app.schemas.enums import ChiefDecision, HumanDecision, TaskStatus


def make_state(**kwargs) -> NewsTaskState:
    return NewsTaskState(task_id="TASK_001", topic="测试选题", **kwargs)


def test_planning_routes_to_reporter_or_ends_on_failure():
    assert routing.route_after_planning(make_state()) == "reporter"
    assert (
        routing.route_after_planning(make_state(task_status=TaskStatus.FAILED))
        == routing.END
    )


def test_linear_routes_follow_pipeline():
    assert routing.route_after_reporter(make_state()) == "editor"
    assert routing.route_after_editor(make_state()) == "fact_checker"
    assert routing.route_after_fact_checker(make_state()) == "chief_review"


def test_review_routes_by_decision():
    assert (
        routing.route_after_review(make_state(chief_decision=ChiefDecision.APPROVE))
        == "publisher"
    )
    assert (
        routing.route_after_review(
            make_state(chief_decision=ChiefDecision.REQUEST_EDIT)
        )
        == "editor"
    )
    assert (
        routing.route_after_review(
            make_state(chief_decision=ChiefDecision.REQUEST_RESEARCH)
        )
        == "reporter"
    )
    assert (
        routing.route_after_review(
            make_state(chief_decision=ChiefDecision.HUMAN_REVIEW)
        )
        == "human_approval"
    )


def test_review_without_decision_ends():
    assert routing.route_after_review(make_state()) == routing.END


def test_failed_task_ends_from_any_agent():
    failed = make_state(task_status=TaskStatus.FAILED)
    assert routing.route_after_reporter(failed) == routing.END
    assert routing.route_after_editor(failed) == routing.END
    assert routing.route_after_fact_checker(failed) == routing.END
    assert routing.route_after_publisher(failed) == routing.END
    assert (
        routing.route_after_review(
            make_state(
                task_status=TaskStatus.FAILED,
                chief_decision=ChiefDecision.APPROVE,
            )
        )
        == routing.END
    )


def test_human_routes_by_decision():
    assert (
        routing.route_after_human_approval(
            make_state(human_decision=HumanDecision.APPROVE)
        )
        == "publisher"
    )
    assert (
        routing.route_after_human_approval(
            make_state(human_decision=HumanDecision.REQUEST_EDIT)
        )
        == "editor"
    )
    assert (
        routing.route_after_human_approval(
            make_state(human_decision=HumanDecision.REQUEST_RESEARCH)
        )
        == "reporter"
    )
    assert (
        routing.route_after_human_approval(
            make_state(human_decision=HumanDecision.TERMINATE)
        )
        == routing.END
    )
    assert routing.route_after_human_approval(make_state()) == routing.END


def test_publisher_and_confirmation_routes():
    assert routing.route_after_publisher(make_state()) == "user_confirmation"
    assert (
        routing.route_after_confirmation(make_state(user_confirmation=True))
        == "publish"
    )
    assert (
        routing.route_after_confirmation(make_state(user_confirmation=False))
        == routing.END
    )
