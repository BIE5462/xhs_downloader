from __future__ import annotations

from typing import Iterable, List, Set

from .models import NoteSummary, SearchFilters


def dedupe_summaries(items: Iterable[NoteSummary]) -> List[NoteSummary]:
    seen: Set[str] = set()
    results: List[NoteSummary] = []
    for item in items:
        if item.note_id in seen:
            continue
        seen.add(item.note_id)
        results.append(item)
    return results


def matches_filters(item: NoteSummary, filters: SearchFilters) -> bool:
    if item.like_count < filters.min_likes:
        return False
    if item.comment_count < filters.min_comments:
        return False
    return True


def filter_summaries(items: Iterable[NoteSummary], filters: SearchFilters) -> List[NoteSummary]:
    return [item for item in items if matches_filters(item, filters)]

