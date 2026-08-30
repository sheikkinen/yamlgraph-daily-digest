"""FR-905 — validate ranked stories at the rank→format boundary.

RED before GREEN. `stories: list[Any]` gives the provider no item
structure, so the model may return objects or strings. Eleven scheduled
runs returned dicts; 2026-08-29 returned strings and crashed the renderer.

The contracts frozen by the judgement:

- non-conforming items are dropped individually, each observably logged
- an invoked ranker that yields no valid survivor RAISES; `invalid` is a
  failure classification, never a successful graph result (R-2)
- an invoked ranker returning an empty list is its own case (R-5)
- `no_articles` means the ranker was never invoked
"""

from __future__ import annotations

import logging

import pytest

from nodes.formatting import InvalidRankedStoriesError, format_markdown

TODAY = "2026-08-30"


def _story(**over):
    base = {
        "title": "A story",
        "url": "https://example.com/a",
        "summary": "A summary.",
        "reason": "Because.",
    }
    base.update(over)
    return base


class TestNoArticles:
    def test_ranker_never_invoked_is_a_quiet_day(self):
        result = format_markdown({"today": TODAY, "ranked_stories": []})
        assert result["digest_status"] == "no_articles"
        assert result["digest_markdown"] == ""


class TestInvalidIsAFailure:
    def test_all_strings_raises(self):
        """The 2026-08-29 production shape."""
        with pytest.raises(InvalidRankedStoriesError) as exc:
            format_markdown(
                {"today": TODAY, "ranked_stories": ["a string", "another"]}
            )
        message = str(exc.value)
        assert "digest_status=invalid" in message
        assert "2" in message, "must name the ranked item count"
        assert "str" in message, "must name the observed element types"

    def test_empty_ranked_payload_from_an_invoked_ranker_raises(self):
        """R-5: neither a quiet day nor a partial response."""
        with pytest.raises(InvalidRankedStoriesError):
            format_markdown(
                {
                    "today": TODAY,
                    "ranked_stories": {"stories": []},
                    "analyzed": [{"x": 1}],
                }
            )

    def test_every_item_malformed_raises(self):
        with pytest.raises(InvalidRankedStoriesError):
            format_markdown(
                {"today": TODAY, "ranked_stories": [{"nope": 1}, {"also": 2}]}
            )

    def test_invalid_is_never_a_successful_result(self):
        """`invalid` exists only in the failure path."""
        result = format_markdown({"today": TODAY, "ranked_stories": [_story()]})
        assert result["digest_status"] != "invalid"


class TestPartialResponses:
    def test_mixed_response_renders_the_conforming_subset(self):
        result = format_markdown(
            {
                "today": TODAY,
                "ranked_stories": [_story(title="Good"), "garbage", {"nope": 1}],
            }
        )
        assert result["digest_status"] == "ready"
        assert "Good" in result["digest_markdown"]
        assert "garbage" not in result["digest_markdown"]

    def test_each_dropped_item_is_observable(self, caplog):
        """R-4: a silent drop discards model output invisibly."""
        with caplog.at_level(logging.WARNING):
            format_markdown(
                {"today": TODAY, "ranked_stories": [_story(), "garbage"]}
            )
        dropped = [r for r in caplog.records if "drop" in r.getMessage().lower()]
        assert dropped, "dropped items must be logged"
        message = dropped[0].getMessage()
        assert "1" in message, "must name the item index"
        assert "str" in message, "must name the observed type"
        assert len(message) < 300, "log the reason, not the whole payload"


class TestBoundaryIsNotAFrameworkChange:
    def test_prompt_schema_is_untouched(self):
        """The guard is correct regardless of what the schema becomes."""
        from pathlib import Path

        schema = (Path(__file__).parent.parent / "prompts/rank_stories.yaml").read_text()
        assert "list[Any]" in schema, (
            "FR-905 guards the boundary; changing the schema is a separate FR"
        )
