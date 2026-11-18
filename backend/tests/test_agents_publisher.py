import asyncio

import pytest
from pydantic import ValidationError

from app.agents.contracts import PublisherInput
from app.agents.publisher import PublisherAgent
from app.schemas.domain import Publication
from app.schemas.enums import (
    AgentStatus,
    ChiefDecision,
    FactCheckOverallResult,
    PublicationStatus,
)
from app.services.publish_service import MockPublishService, PublishError
from tests.fakes import make_article


class StubPublishService:
    def __init__(self, *, error: PublishError | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self._error = error

    async def publish(self, *, article_id: str, article_version: int) -> Publication:
        self.calls.append((article_id, article_version))
        if self._error is not None:
            raise self._error
        raise AssertionError("该测试不应调用发布接口")


def make_input(*, confirm: bool = False) -> PublisherInput:
    return PublisherInput(
        task_id="TASK_001",
        article_id="ART_0001",
        article=make_article(),
        article_version=2,
        chief_decision=ChiefDecision.APPROVE,
        fact_check_status=FactCheckOverallResult.PASSED,
        user_confirmation=confirm,
    )


def run_agent(agent: PublisherAgent, payload: PublisherInput):
    return asyncio.run(agent.run(payload))


def test_publisher_creates_pending_record_without_confirmation():
    service = StubPublishService()
    output = run_agent(PublisherAgent(publish_service=service), make_input())

    assert output.status == AgentStatus.COMPLETED
    assert output.publication is not None
    assert output.publication.status == PublicationStatus.PENDING_PUBLISH
    assert output.publication.article_version == 2
    assert service.calls == []


def test_publisher_publishes_after_confirmation():
    service = MockPublishService()
    output = run_agent(
        PublisherAgent(publish_service=service), make_input(confirm=True)
    )

    assert output.status == AgentStatus.COMPLETED
    publication = output.publication
    assert publication is not None
    assert publication.status == PublicationStatus.PUBLISHED
    assert publication.published_at is not None
    assert publication.external_url == "https://newsroom.local/articles/ART_0001/v2"


def test_publisher_is_idempotent_for_same_article_version():
    service = MockPublishService()
    agent = PublisherAgent(publish_service=service)

    first = run_agent(agent, make_input(confirm=True))
    second = run_agent(agent, make_input(confirm=True))

    assert first.publication is not None and second.publication is not None
    assert first.publication.publication_id == second.publication.publication_id


def test_publisher_keeps_pending_when_channel_fails():
    service = MockPublishService(fail_times=1, failure_message="接口超时")
    output = run_agent(
        PublisherAgent(publish_service=service), make_input(confirm=True)
    )

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "PUBLISH_FAILED"
    assert output.error.retryable is True
    assert output.publication is not None
    assert output.publication.status == PublicationStatus.PENDING_PUBLISH
    assert "接口超时" in (output.publication.message or "")


def test_publisher_can_retry_after_channel_failure():
    service = MockPublishService(fail_times=1)
    agent = PublisherAgent(publish_service=service)

    failed = run_agent(agent, make_input(confirm=True))
    retried = run_agent(agent, make_input(confirm=True))

    assert failed.status == AgentStatus.FAILED
    assert retried.status == AgentStatus.COMPLETED
    assert retried.publication is not None
    assert retried.publication.status == PublicationStatus.PUBLISHED


def test_publisher_rejects_unapproved_decision_bypassing_contract():
    payload = PublisherInput.model_construct(
        task_id="TASK_001",
        article_id="ART_0001",
        article=make_article(),
        article_version=2,
        chief_decision=ChiefDecision.HUMAN_REVIEW,
        fact_check_status=FactCheckOverallResult.PASSED,
        user_confirmation=True,
    )
    output = run_agent(PublisherAgent(), payload)

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "PUBLISH_NOT_APPROVED"


def test_publisher_rejects_failed_fact_check_bypassing_contract():
    payload = PublisherInput.model_construct(
        task_id="TASK_001",
        article_id="ART_0001",
        article=make_article(),
        article_version=2,
        chief_decision=ChiefDecision.APPROVE,
        fact_check_status=FactCheckOverallResult.FAILED,
        user_confirmation=True,
    )
    output = run_agent(PublisherAgent(), payload)

    assert output.status == AgentStatus.FAILED
    assert output.error is not None
    assert output.error.code == "PUBLISH_FACT_CHECK_FAILED"


def test_publisher_contract_rejects_unapproved_input():
    with pytest.raises(ValidationError):
        PublisherInput(
            task_id="TASK_001",
            article_id="ART_0001",
            article=make_article(),
            article_version=2,
            chief_decision=ChiefDecision.REQUEST_EDIT,
            fact_check_status=FactCheckOverallResult.PASSED,
        )
