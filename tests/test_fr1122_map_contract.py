"""FR-1122 — `analyze_all` on the FR-1073 / FR-939 map contract.

RED before GREEN. The map was written against the map contract yamlgraph 0.6.0
ships: `on_error: skip` at map level (never read by the compiler), no
`state_key` on the sub-node (items collected under a generated
`_map_analyze_all_sub` wrapper the ranker prompt reaches into), no cap
policy, no timeout, no failures key, and a runner that never reads the map
verdict. Under FR-1073 the same declaration makes one failed article an
untolerated failure and a run-killing `MapCompletenessError`.

Witnesses (judgement AC-01..AC-08). Every compiled-contract test loads the
REAL graph, stubs every Python tool and the LLM call, and drives the map
through the framework — it never inspects YAML alone. AC-09 (the exact
release floor) is enforced by the workflow file once that release exists.
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import jinja2
import pytest
import yaml

from yamlgraph.models.map_results import MapCompletenessError, MapFailure, MapVerdict

REPO = Path(__file__).resolve().parents[1]
GRAPH = REPO / "graph.yaml"
PROMPT = REPO / "prompts" / "rank_stories.yaml"
COLLECT = REPO / "sources" / "hn_rss.tool.yaml"

MAP = "analyze_all"


def _graph() -> dict:
    return yaml.safe_load(GRAPH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- AC-01 / AC-07 / AC-08 (shape)


class TestDeclaredShape:
    def test_map_declares_the_contract_keys(self):
        node = _graph()["nodes"][MAP]
        assert node.get("max_items") == 100
        assert node.get("on_overflow") == "truncate"
        assert node.get("timeout") == 120
        assert node.get("failures") == "analysis_failures"
        assert node["collect"] == "analyzed"

    def test_policy_lives_on_the_sub_node_not_the_map(self):
        node = _graph()["nodes"][MAP]
        assert "on_error" not in node, "map-level on_error is never read"
        assert node["node"].get("on_error") == "skip"
        assert node["node"].get("state_key") == "analysis"

    def test_gate_declares_output(self):
        assert _graph()["nodes"]["gate"].get("output"), "E601: silent passthrough"

    def test_max_concurrency_is_declared_and_parsed(self):
        from yamlgraph.compile.graph_loader import load_graph_config

        assert _graph().get("config", {}).get("max_concurrency") == 8
        config = load_graph_config(GRAPH, tool_bindings={"collect": str(COLLECT)})
        assert config.max_concurrency == 8


# ---------------------------------------------------------------- AC-02 (flat prompt)


class TestFlatRankerPrompt:
    def test_no_generated_wrapper_is_referenced(self):
        assert "_map_" not in PROMPT.read_text(encoding="utf-8")

    def test_renders_two_flat_items(self):
        user = yaml.safe_load(PROMPT.read_text(encoding="utf-8"))["user"]
        analyzed = [
            {"title": "First flat", "url": "u1", "summary": "s1", "relevance_score": 0.9},
            {"title": "Second flat", "url": "u2", "summary": "s2", "relevance_score": 0.4},
        ]
        rendered = jinja2.Template(user).render(analyzed=analyzed, topics=["AI"])
        assert "First flat" in rendered and "Second flat" in rendered
        assert "u1" in rendered and "s2" in rendered


# ---------------------------------------------------------------- compiled contract helpers


def _article(title: str) -> dict:
    return {
        "title": title,
        "url": f"https://example.com/{title}",
        "source": "test",
        "timestamp": "2026-09-27T00:00:00",
        "content": f"content of {title}",
    }


def _stub_tools(articles: list[dict], calls: list[str]) -> Callable[..., Callable]:
    canned: dict[str, dict[str, Any]] = {
        "collect": {"raw_articles": articles},
        "filter_recent": {"filtered_articles": articles},
        "fetch_article_content": {"articles_with_content": articles},
        # Route to END after the map+ranker: the gate reads no_articles.
        "format_markdown": {
            "digest_markdown": "",
            "digest_html": "",
            "digest_status": "no_articles",
        },
        "write_bulletin": {"bulletin_path": None},
        "send_email": {"sent": None},
    }

    def fake_loader(config: Any, *, tool_name: str = "", **_: Any) -> Callable:
        update = canned[tool_name]

        def tool(state: dict) -> dict:
            calls.append(tool_name)
            return dict(update)

        return tool

    return fake_loader


def _fake_llm(analyze_calls: list[str], *, slow_for: str | None = None) -> Callable:
    """`execute_prompt` stand-in: analysis per article; 'poison' raises; slow sleeps."""

    def execute(*, prompt_name: str, variables: dict, **_: Any) -> Any:
        if prompt_name == "rank_stories":
            return {"stories": []}
        title = variables["title"]
        analyze_calls.append(title)
        if title == "poison":
            raise RuntimeError("unparseable article")
        if slow_for is not None and title == slow_for:
            time.sleep(0.8)
        return {
            "title": title,
            "url": variables["url"],
            "summary": f"summary of {title}",
            "relevance_score": 0.5,
            "key_insight": "k",
            "category": "AI",
        }

    return execute


def _run(
    articles: list[dict],
    *,
    mutate: Callable[[dict], None] | None = None,
    slow_for: str | None = None,
) -> tuple[dict, list[str]]:
    from yamlgraph.compile.graph_loader import compile_graph, load_graph_config

    calls: list[str] = []
    analyze_calls: list[str] = []
    with (
        patch(
            "yamlgraph.compile.graph_loader.load_python_function",
            side_effect=_stub_tools(articles, calls),
        ),
        patch(
            "yamlgraph.tools.python_tool.load_python_function",
            side_effect=_stub_tools(articles, calls),
        ),
        patch(
            "yamlgraph.node_factory.llm_nodes.execute_prompt",
            side_effect=_fake_llm(analyze_calls, slow_for=slow_for),
        ),
    ):
        config = load_graph_config(GRAPH, tool_bindings={"collect": str(COLLECT)})
        if mutate is not None:
            mutate(config.nodes[MAP])
        app = compile_graph(config).compile()
        result = app.invoke({"topics": ["AI"], "today": "2026-09-27"})
    return result, analyze_calls


# ---------------------------------------------------------------- AC-03 (skip vs strict)


class TestNestedSkipIsTolerated:
    def test_one_skipped_article_yields_two_flat_rows_and_a_tolerated_failure(self):
        result, _ = _run([_article("a"), _article("poison"), _article("c")])
        analyzed = result["analyzed"]
        assert [row["title"] for row in analyzed] == ["a", "c"]
        assert all("_map_analyze_all_sub" not in row for row in analyzed)
        failures = [MapFailure.model_validate(f) for f in result["analysis_failures"]]
        assert len(failures) == 1 and failures[0].tolerated is True
        verdict = MapVerdict.model_validate(result["_map_verdict"][MAP])
        assert verdict.met and verdict.dispatched == 3 and verdict.succeeded == 2

    def test_without_nested_skip_the_same_branch_is_untolerated_and_raises(self):
        def drop_skip(node: dict) -> None:
            node["node"].pop("on_error", None)

        with pytest.raises(MapCompletenessError):
            _run([_article("a"), _article("poison"), _article("c")], mutate=drop_skip)


# ---------------------------------------------------------------- AC-04 (timeout)


class TestTimeoutIsNeverTolerated:
    def test_slow_branch_fails_untolerated_despite_nested_skip(self):
        def short_timeout(node: dict) -> None:
            node["timeout"] = 0.2

        with pytest.raises(MapCompletenessError):
            _run([_article("a"), _article("slow")], mutate=short_timeout, slow_for="slow")


# ---------------------------------------------------------------- AC-05 (overflow)


class TestOverflowTruncates:
    def test_101_inputs_run_exactly_100_with_one_warning(self, caplog):
        articles = [_article(f"n{i:03d}") for i in range(101)]
        with caplog.at_level(logging.WARNING, logger="yamlgraph.compile.map_compiler"):
            result, analyze_calls = _run(articles)
        assert len(analyze_calls) == 100
        assert sorted(analyze_calls) == [f"n{i:03d}" for i in range(100)]
        warnings = [
            r for r in caplog.records if "truncating" in r.getMessage() and MAP in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "101" in warnings[0].getMessage() and "max_items=100" in warnings[0].getMessage()
        assert MapVerdict.model_validate(result["_map_verdict"][MAP]).dispatched == 100


# ---------------------------------------------------------------- AC-07 (lint) / AC-08 (compile)


class TestLintAndCompile:
    def test_lint_is_free_of_the_four_map_diagnostics(self):
        from yamlgraph.linter.graph_linter import lint_graph

        codes = {issue.code for issue in lint_graph(GRAPH, project_root=REPO).issues}
        assert not codes & {"E601", "W013", "W017", "W022"}, codes

    def test_compile_check_has_the_contract_nodes(self):
        from yamlgraph.compile.graph_loader import compile_graph, load_graph_config

        config = load_graph_config(GRAPH, tool_bindings={"collect": str(COLLECT)})
        nodes = set(compile_graph(config).compile().get_graph().nodes)
        assert {"_map_analyze_all_sub", "_map_analyze_all_account", "_map_analyze_all_join"} <= nodes


# ---------------------------------------------------------------- AC-06 (typed runner report)


class _FakeCompiled:
    def __init__(self, result: dict):
        self._result = result

    def compile(self):
        return self

    def invoke(self, _state: dict) -> dict:
        return self._result


def _runner_result(**over: Any) -> dict:
    base = {
        "raw_articles": [{}] * 3,
        "filtered_articles": [{}] * 3,
        "analyzed": [{"title": "a"}, {"title": "c"}],
        "analysis_failures": [
            MapFailure(
                map=MAP, dispatch="d1", index=1, error_type="Skipped",
                message="unparseable article", node="_map_analyze_all_sub", tolerated=True,
            )
        ],
        "_map_verdict": {
            MAP: MapVerdict(
                dispatch="d1", dispatched=3, succeeded=2, tolerated=1, failed=0,
                accepted=3, min_success=3, met=True,
            )
        },
        "digest_status": "no_articles",
        "errors": [],
    }
    base.update(over)
    return base


def _run_runner(result: dict, monkeypatch) -> None:
    import run_digest

    monkeypatch.setattr(sys, "argv", ["run_digest.py"])
    with (
        patch("yamlgraph.compile.graph_loader.load_graph_config", return_value=object()),
        patch("yamlgraph.compile.graph_loader.compile_graph", return_value=_FakeCompiled(result)),
    ):
        run_digest.main()


class TestRunnerReportsTypedVerdict:
    def test_prints_analysed_counts_and_each_skip(self, monkeypatch, capsys):
        _run_runner(_runner_result(), monkeypatch)
        out = capsys.readouterr().out
        assert "Analysed 2 of 3 - 1 skipped" in out
        assert "skipped #1: Skipped: unparseable article" in out

    def test_missing_verdict_is_loud(self, monkeypatch):
        with pytest.raises(RuntimeError, match="verdict"):
            _run_runner(_runner_result(_map_verdict={}), monkeypatch)
