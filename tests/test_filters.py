import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xhs_downloader.domain.filters import dedupe_summaries, filter_summaries
from xhs_downloader.domain.models import NoteSummary, SearchFilters


class FilterTests(unittest.TestCase):
    def test_filter_applies_like_and_comment_thresholds(self) -> None:
        items = [
            NoteSummary("1", "a", "u1", 100, 10, "https://example.com/1", 1),
            NoteSummary("2", "b", "u2", 20, 1, "https://example.com/2", 2),
            NoteSummary("3", "c", "u3", 99, 30, "https://example.com/3", 3),
        ]
        filters = SearchFilters(min_likes=50, min_comments=5)

        matched = filter_summaries(items, filters)

        self.assertEqual(["1", "3"], [item.note_id for item in matched])

    def test_dedupe_keeps_first_seen_summary(self) -> None:
        items = [
            NoteSummary("1", "first", "u1", 100, 10, "https://example.com/1", 1),
            NoteSummary("1", "second", "u2", 200, 20, "https://example.com/1b", 2),
            NoteSummary("2", "third", "u3", 300, 30, "https://example.com/2", 3),
        ]

        results = dedupe_summaries(items)

        self.assertEqual(2, len(results))
        self.assertEqual("first", results[0].title)


if __name__ == "__main__":
    unittest.main()
