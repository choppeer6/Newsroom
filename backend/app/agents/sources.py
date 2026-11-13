"""Source normalization, de-duplication and ID assignment."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from app.schemas.domain import ResearchSource
from app.tools.search import SearchHit


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def next_source_index(existing: list[ResearchSource], prefix: str) -> int:
    marker = f"{prefix}_"
    highest = 0
    for source in existing:
        if not source.source_id.startswith(marker):
            continue
        suffix = source.source_id[len(marker):]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest + 1


def merge_sources(
    existing: list[ResearchSource],
    hits: list[SearchHit],
    *,
    prefix: str = "SRC",
    limit: int = 12,
) -> list[ResearchSource]:
    merged = list(existing)
    seen = {normalize_url(source.url) for source in existing}
    index = next_source_index(existing, prefix)

    for hit in hits:
        if len(merged) >= limit:
            break
        key = normalize_url(hit.url)
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            ResearchSource(
                source_id=f"{prefix}_{index:04d}",
                title=hit.title.strip() or hit.url,
                url=hit.url,
                published_at=hit.published_at,
                summary=hit.summary.strip() or None,
            )
        )
        index += 1

    return merged


def dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
