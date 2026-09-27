#!/usr/bin/env python3
"""Run the daily digest pipeline.

Usage:
    python run_digest.py --db digest.db --output digests
    python run_digest.py --collect sources/arxiv.tool.yaml --topics "AI"

Archiving and delivery are graph nodes (FR-903), not runner logic: the
ordering — gate, then archive, then send — is an edge in graph.yaml, so a
second digest inherits it instead of copying this script.

Collection is a tool slot (FR-904), so the source is chosen here rather
than named in the graph. A digest over a different subject area is a
--collect binding and a --topics list.

There is no dry mode. Running it IS the intent.
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

REPO_DIR = Path(__file__).parent.resolve()
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def main():
    """Run the daily digest pipeline."""
    parser = argparse.ArgumentParser(description="Run daily digest")
    parser.add_argument("--topics", default="AI,Python,LangGraph")
    parser.add_argument("--db", default="digest.db")
    parser.add_argument("--output", default="digests")
    parser.add_argument(
        "--collect",
        default="sources/hn_rss.tool.yaml",
        help="Tool manifest binding the graph's `collect` slot (FR-904)",
    )
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=24,
        help="Recency window; widen it for sources that publish on a "
        "slower cadence than hourly news (arXiv announces weekdays only)",
    )
    args = parser.parse_args()

    os.environ["DATABASE_PATH"] = args.db

    from yamlgraph.compile.graph_loader import compile_graph, load_graph_config

    # Slot binding paths resolve against CWD; anchor them to the repo so
    # the runner works from anywhere, as the scheduled job needs.
    config = load_graph_config(
        REPO_DIR / "graph.yaml",
        tool_bindings={"collect": str(REPO_DIR / args.collect)},
    )
    compiled = compile_graph(config).compile()

    result = compiled.invoke(
        {
            "topics": [t.strip() for t in args.topics.split(",")],
            "today": date.today().isoformat(),
            "output_dir": args.output,
            "max_age_hours": args.max_age_hours,
        }
    )

    # FR-1121: a recorded error never becomes a quiet day. A node without
    # on_error falls through to the framework's default handler, which
    # records a PipelineError and continues; nothing downstream may treat
    # the resulting absence as "no articles". Tolerated map skips (FR-1073)
    # never enter `errors`, so a skipped article does not trip this.
    errors = result.get("errors") or []
    if errors:
        for err in errors:
            node = getattr(err, "node", None) or "?"
            message = getattr(err, "message", None) or str(err)
            print(f"✗ {node}: {message}", file=sys.stderr)
        sys.exit(2)

    print(f"✓ Found {len(result.get('raw_articles', []))} articles")
    print(f"✓ After filtering: {len(result.get('filtered_articles', []))}")

    # FR-1122: the map verdict and failures are typed records (FR-1073);
    # validate at the boundary and read attributes. A missing verdict is
    # a loud failure, never a "?". Composed after the FR-1121 guard above:
    # an untolerated failure raises at the join and never reaches here.
    from yamlgraph.models.map_results import MapFailure, MapVerdict

    verdict_raw = (result.get("_map_verdict") or {}).get("analyze_all")
    if verdict_raw is None:
        raise RuntimeError("analyze_all map verdict is missing")
    verdict = MapVerdict.model_validate(verdict_raw)
    failures = [
        MapFailure.model_validate(item)
        for item in (result.get("analysis_failures") or [])
    ]
    print(
        f"✓ Analysed {verdict.succeeded} of {verdict.dispatched}"
        f" - {len(failures)} skipped"
    )
    for failure in failures:
        print(
            f"  · skipped #{failure.index}: {failure.error_type}:"
            f" {failure.message[:120]}"
        )

    if result.get("digest_status") == "no_articles":
        print("digest: no-op — no new stories, nothing to commit")
        return

    # tool_call wraps returns in a {success, result, error} envelope.
    archived = (result.get("bulletin_path") or {}).get("result", {})
    delivered = (result.get("sent") or {}).get("result", {})
    print(f"✓ Archived {archived.get('path', '?')}")
    print(f"✓ Delivered to {', '.join(delivered.get('to', ['?']))}")


if __name__ == "__main__":
    main()
