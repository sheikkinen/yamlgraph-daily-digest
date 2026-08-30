"""FR-904 — collection is a slot, not a hardcoded fetcher.

The claim under test is that a second digest is a *binding*, not a fork.
That claim is only falsifiable with two bindings, so both are exercised
here against one unchanged graph file.

Network is never touched: each collector's transport is injected, which
also pins the collector ABI as a real function signature rather than a
table in a document.
"""

import hashlib
import sys
from pathlib import Path

import pytest
import yaml

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

from yamlgraph.tools.tool_slots import (  # noqa: E402
    ToolSlotBindingError,
    resolve_tool_slots,
)

REQUIRED_KEYS = {"title", "url", "source", "timestamp"}


def _graph() -> dict:
    return yaml.safe_load((REPO_DIR / "graph.yaml").read_text())


def _graph_hash() -> str:
    return hashlib.sha256((REPO_DIR / "graph.yaml").read_bytes()).hexdigest()


class TestTheSlotIsDeclared:
    def test_collect_is_a_slot_with_a_contract(self):
        collect = _graph()["tools"]["collect"]

        assert collect["slot"] is True
        assert collect["contract"]["runtimes"] == ["python"]
        assert collect["contract"]["args"] == ["config"]

    def test_the_graph_no_longer_names_a_source(self):
        """A pipeline that names its source cannot be bound to another."""
        text = (REPO_DIR / "graph.yaml").read_text()

        assert "nodes.sources" not in text
        assert "fetch_sources" not in text


class TestBothBindingsSatisfyTheContract:
    """One binding proves nothing: it is an inline tool with ceremony."""

    @pytest.mark.parametrize(
        "manifest_path",
        ["sources/hn_rss.tool.yaml", "sources/arxiv.tool.yaml"],
    )
    def test_binding_resolves(self, manifest_path):
        """Resolution replaces the slot with a translated FR-768 tool, so
        execution reuses the existing python runtime rather than a new
        engine."""
        resolved = resolve_tool_slots(
            _graph()["tools"], {"collect": manifest_path}, REPO_DIR
        )["collect"]

        assert "slot" not in resolved
        assert resolved["type"] == "python"
        assert resolved["function"] == "collect"

    @pytest.mark.parametrize(
        "manifest_path",
        ["sources/hn_rss.tool.yaml", "sources/arxiv.tool.yaml"],
    )
    def test_manifest_points_at_a_real_collector(self, manifest_path):
        manifest = yaml.safe_load((REPO_DIR / manifest_path).read_text())
        impl = REPO_DIR / "sources" / manifest["runtime"]["path"]

        assert manifest["runtime"]["type"] == "python"
        assert manifest["runtime"]["function"] == "collect"
        assert impl.exists()

    def test_switching_bindings_does_not_touch_the_graph(self):
        """The acceptance criterion, stated as a hash rather than a promise."""
        before = _graph_hash()

        for binding in ("sources/hn_rss.tool.yaml", "sources/arxiv.tool.yaml"):
            resolve_tool_slots(_graph()["tools"], {"collect": binding}, REPO_DIR)

        assert _graph_hash() == before


class TestCollectorABI:
    """A binding that satisfies the slot but changes the output shape
    breaks filtering, extraction, and ranking downstream. Both directions
    of the contract are checked."""

    def test_hn_rss_records_carry_every_required_key(self):
        from sources.hn_rss import collect

        result = collect(
            config={},
            http_get=_fake_hn_transport(),
            rss_parse=_fake_rss_transport(),
        )

        assert result["raw_articles"]
        for record in result["raw_articles"]:
            assert REQUIRED_KEYS <= set(record)

    def test_arxiv_records_carry_every_required_key(self):
        from sources.arxiv import collect

        result = collect(config={}, feed_parse=_fake_arxiv_transport())

        assert result["raw_articles"]
        for record in result["raw_articles"]:
            assert REQUIRED_KEYS <= set(record)

    def test_arxiv_is_genuinely_a_different_source(self):
        """Not a second HN in disguise — the label reaches the bulletin."""
        from sources.arxiv import collect

        result = collect(config={}, feed_parse=_fake_arxiv_transport())

        assert {r["source"] for r in result["raw_articles"]} == {"arXiv"}

    def test_timestamps_are_parseable_by_the_downstream_filter(self):
        """filter_recent parses this string for the cutoff; an
        unparseable timestamp degrades silently to 'not recent'."""
        from datetime import datetime

        from sources.arxiv import collect

        for record in collect(config={}, feed_parse=_fake_arxiv_transport())[
            "raw_articles"
        ]:
            datetime.fromisoformat(record["timestamp"])


class TestCadenceBelongsToTheSource:
    """arXiv announces on weekdays only. Measured on a Saturday, its
    freshest cs.AI submission was 3 days old, so the pipeline's 24h
    cutoff emptied the digest entirely — a second binding that yields
    nothing five days a week proves nothing about the slot."""

    def _articles(self, age_hours: int) -> list[dict]:
        from datetime import datetime, timedelta

        stamp = (datetime.now() - timedelta(hours=age_hours)).isoformat()
        return [
            {
                "title": "A preprint",
                "url": f"https://arxiv.org/abs/{age_hours}",
                "source": "arXiv",
                "timestamp": stamp,
            }
        ]

    def test_default_window_is_still_a_day(self, tmp_path, monkeypatch):
        from nodes.filters import filter_recent

        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "d.db"))

        assert filter_recent({"raw_articles": self._articles(72)})[
            "filtered_articles"
        ] == []

    def test_a_slower_source_can_widen_the_window(self, tmp_path, monkeypatch):
        from nodes.filters import filter_recent

        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "d.db"))

        result = filter_recent(
            {"raw_articles": self._articles(72), "max_age_hours": 96}
        )

        assert len(result["filtered_articles"]) == 1


class TestConstantsMovedWithTheirImplementation:
    def test_the_shared_source_module_is_retired(self):
        """Swapping sources should swap files. A feed list in a shared
        module is a source the graph still owns — and a hollowed-out
        module is a fork waiting to happen, so it goes entirely."""
        assert not (REPO_DIR / "nodes" / "sources.py").exists()

        import nodes

        for retired in ("fetch_sources", "fetch_hn", "fetch_rss"):
            assert not hasattr(nodes, retired)

    def test_each_source_owns_its_own_endpoints(self):
        import sources.arxiv as arxiv
        import sources.hn_rss as hn_rss

        assert hn_rss.RSS_FEEDS
        assert hn_rss.HN_API_BASE
        assert arxiv.ARXIV_FEED


class TestBindingFailuresAreLoudAndEarly:
    """FR-892 semantics, reused exactly — every failure raises before any
    node or LLM executes, so a contaminated run costs nothing."""

    def test_missing_binding_raises(self):
        with pytest.raises(ToolSlotBindingError, match="Missing --tool"):
            resolve_tool_slots(_graph()["tools"], {}, REPO_DIR)

    def test_binding_an_undeclared_slot_raises(self):
        with pytest.raises(ToolSlotBindingError, match="undeclared"):
            resolve_tool_slots(
                _graph()["tools"],
                {
                    "collect": "sources/hn_rss.tool.yaml",
                    "nonesuch": "sources/arxiv.tool.yaml",
                },
                REPO_DIR,
            )

    def test_runtime_outside_the_allowlist_raises(self, tmp_path):
        shell_manifest = tmp_path / "shell.tool.yaml"
        shell_manifest.write_text(
            yaml.safe_dump(
                {
                    "name": "shell_collect",
                    "description": "a collector the contract does not allow",
                    "runtime": {"type": "shell", "command": "echo {config}"},
                }
            )
        )

        with pytest.raises(ToolSlotBindingError, match="contract allows"):
            resolve_tool_slots(
                _graph()["tools"], {"collect": str(shell_manifest)}, REPO_DIR
            )

    def test_a_missing_manifest_file_raises(self):
        with pytest.raises(ToolSlotBindingError):
            resolve_tool_slots(
                _graph()["tools"], {"collect": "sources/nope.tool.yaml"}, REPO_DIR
            )


def _fake_hn_transport():
    """Stands in for httpx.get against the HN firebase API."""

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def http_get(url, timeout=10):
        if "topstories" in url:
            return _Resp([101, 102])
        return _Resp(
            {
                "type": "story",
                "title": f"Story {url}",
                "url": "https://example.com/a",
                "time": 1735689600,
            }
        )

    return http_get


def _fake_rss_transport():
    """Stands in for feedparser.parse against an RSS feed."""

    class _Entry:
        title = "An RSS article"
        link = "https://example.com/rss"
        published_parsed = (2026, 8, 30, 6, 0, 0, 0, 0, 0)

    class _Feed:
        entries = [_Entry()]

    return lambda url: _Feed()


def _fake_arxiv_transport():
    """Stands in for feedparser.parse against the arXiv Atom feed."""

    class _Entry:
        title = "Attention Is Still All You Need"
        link = "https://arxiv.org/abs/2608.00001"
        published_parsed = (2026, 8, 30, 6, 0, 0, 0, 0, 0)

    class _Feed:
        entries = [_Entry()]

    return lambda url: _Feed()
