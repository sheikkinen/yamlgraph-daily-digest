"""FR-1121 — the ranker survives constrained decoding and fails loudly.

RED before GREEN. Nine scheduled runs (2026-09-19..27) completed green and
published nothing: yamlgraph 0.5.25 (FR-998) binds Anthropic nodes with
constrained decoding, the SDK's strict transform rejected
``stories: list[Any]`` (untyped items), ``rank_stories`` declared no
``on_error``, the framework's default handler let the graph continue with
an absent result, ``format_markdown`` read the absence as a quiet day, and
``run_digest.py`` printed the no-op line and exited 0.

Witnesses (judgement AC-02..AC-06):

- the committed ranker prompt model passes the Anthropic SDK transform
  (offline; the oracle is the SDK's own function);
- ``rank_stories`` declares ``on_error: fail`` (shape);
- with the real graph compiled and the ranker forced to raise, the ORIGINAL
  exception propagates from graph invocation and ``format_markdown`` is
  never invoked (behaviour);
- a completed invocation carrying recorded errors and ``no_articles`` makes
  the runner print every error to stderr, print no no-op line, and exit 2.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from yamlgraph.models import PipelineError

REPO = Path(__file__).resolve().parents[1]
PROMPT = REPO / "prompts" / "rank_stories.yaml"
GRAPH = REPO / "graph.yaml"
COLLECT = REPO / "sources" / "hn_rss.tool.yaml"


RANKER_FIELDS = {"title", "url", "summary", "relevance", "reason"}


def _ranker_model() -> type:
    from yamlgraph.schema_loader import load_schema_from_yaml

    model = load_schema_from_yaml(PROMPT)
    assert model is not None
    return model


class TestRankerSchema:
    def test_transformed_items_keep_every_story_field(self):
        """FR-1125 content witness: `list[dict]` passed the raise-only check and the
        model answered []; the assertion is now preservation of the five fields."""
        transform_schema = pytest.importorskip("anthropic").transform_schema
        transformed = transform_schema(copy.deepcopy(_ranker_model().model_json_schema()))
        items = transformed["properties"]["stories"]["items"]
        if "$ref" in items:
            items = transformed["$defs"][items["$ref"].rsplit("/", 1)[-1]]
        assert set(items["properties"]) == RANKER_FIELDS
        assert set(items.get("required", [])) == RANKER_FIELDS
        assert items.get("additionalProperties") is False

    def test_rank_stories_declares_on_error_fail(self):
        config = yaml.safe_load(GRAPH.read_text(encoding="utf-8"))
        assert config["nodes"]["rank_stories"].get("on_error") == "fail"


class _RankerBoom(RuntimeError):
    """Distinct type: the witness proves identity, not merely 'something raised'."""


def _stub_tools(calls: list[str]) -> Callable[..., Callable[[dict], dict]]:
    """Replace every Python tool with a canned function; the map dispatches zero items."""
    canned: dict[str, dict[str, Any]] = {
        "collect": {"raw_articles": []},
        "filter_recent": {"filtered_articles": []},
        "fetch_article_content": {"articles_with_content": []},
        "format_markdown": {
            "digest_markdown": "",
            "digest_html": "",
            "digest_status": "no_articles",
        },
        # tool_call manifests are loaded at compile time too; never reached here.
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


class TestRankerFailureIsLoud:
    def test_original_exception_propagates_and_formatting_never_runs(self):
        from yamlgraph.compile.graph_loader import compile_graph, load_graph_config

        calls: list[str] = []
        fake_loader = _stub_tools(calls)

        def boom(*, prompt_name: str, **_: Any) -> Any:
            raise _RankerBoom(f"forced failure in {prompt_name}")

        with (
            patch(
                "yamlgraph.compile.graph_loader.load_python_function",
                side_effect=fake_loader,
            ),
            patch(
                "yamlgraph.tools.python_tool.load_python_function",
                side_effect=fake_loader,
            ),
            patch("yamlgraph.node_factory.llm_nodes.execute_prompt", side_effect=boom),
        ):
            config = load_graph_config(GRAPH, tool_bindings={"collect": str(COLLECT)})
            app = compile_graph(config).compile()
            # RED on main: returns normally with digest_status == no_articles.
            with pytest.raises(_RankerBoom):
                app.invoke({"topics": ["AI"], "today": "2026-09-27"})

        assert "collect" in calls, "the run must have reached the graph at all"
        assert "format_markdown" not in calls, "formatting ran after a failed ranker"


class _FakeCompiled:
    def __init__(self, result: dict):
        self._result = result

    def compile(self):
        return self

    def invoke(self, _state: dict) -> dict:
        return self._result


class TestRunnerRefusesQuietDayWithErrors:
    def test_recorded_errors_exit_2_before_any_noop_line(self, monkeypatch, capsys):
        import run_digest

        errors = [
            PipelineError(type="unknown_error", message="Schema must have a 'type'", node="rank_stories"),
            PipelineError(type="unknown_error", message="second failure", node="rank_stories"),
        ]
        result = {
            "raw_articles": [{}] * 3,
            "filtered_articles": [{}] * 2,
            "digest_status": "no_articles",
            "errors": errors,
        }
        monkeypatch.setattr(sys, "argv", ["run_digest.py"])
        with (
            patch("yamlgraph.compile.graph_loader.load_graph_config", return_value=object()),
            patch(
                "yamlgraph.compile.graph_loader.compile_graph",
                return_value=_FakeCompiled(result),
            ),
        ):
            with pytest.raises(SystemExit) as exc:
                run_digest.main()

        assert exc.value.code == 2
        out, err = capsys.readouterr()
        assert "no-op" not in out, "a recorded error must never print the quiet-day line"
        assert "rank_stories" in err
        assert "Schema must have a 'type'" in err
        assert "second failure" in err
