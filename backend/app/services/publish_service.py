"""Mock publishing channel used until a real publishing API is wired in."""

from __future__ import annotations

from typing import Protocol

from app.core.utils import generate_id, utc_now
from app.schemas.domain import Publication
from app.schemas.enums import PublicationStatus


class PublishError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


class PublishService(Protocol):
    async def publish(self, *, article_id: str, article_version: int) -> Publication: ...


class MockPublishService:
    """Idempotent in-memory publishing channel keyed by (article_id, version)."""

    def __init__(
        self,
        *,
        base_url: str = "https://newsroom.local/articles",
        fail_times: int = 0,
        failure_message: str = "发布接口暂时不可用",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._fail_times = fail_times
        self._failure_message = failure_message
        self._published: dict[tuple[str, int], Publication] = {}

    async def publish(self, *, article_id: str, article_version: int) -> Publication:
        key = (article_id, article_version)
        existing = self._published.get(key)
        if existing is not None:
            return existing.model_copy(deep=True)

        if self._fail_times > 0:
            self._fail_times -= 1
            raise PublishError(self._failure_message)

        now = utc_now()
        publication = Publication(
            publication_id=generate_id("PUB"),
            article_id=article_id,
            article_version=article_version,
            status=PublicationStatus.PUBLISHED,
            confirmed_by="user",
            confirmed_at=now,
            published_at=now,
            external_url=f"{self._base_url}/{article_id}/v{article_version}",
            message="发布成功",
        )
        self._published[key] = publication
        return publication.model_copy(deep=True)
