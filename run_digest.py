#!/usr/bin/env python3
"""Run the daily digest pipeline and write a markdown bulletin.

Usage:
    python run_digest.py --db digest.db --output digests/
    python run_digest.py --dry-run   # print bulletin, write nothing
"""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

REPO_DIR = Path(__file__).parent.resolve()
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

INDEX_START = "<!-- digest-index -->"
INDEX_END = "<!-- /digest-index -->"
INDEX_SIZE = 14


def update_readme_index(readme_path: Path, digests_dir: Path) -> None:
    """Rewrite the digest-index block with the latest bulletins."""
    bulletins = sorted(digests_dir.glob("*.md"), reverse=True)[:INDEX_SIZE]
    entries = "\n".join(
        f"- [{p.stem}]({digests_dir.name}/{p.name})" for p in bulletins
    )
    block = f"{INDEX_START}\n{entries}\n{INDEX_END}"
    text = readme_path.read_text()
    new_text = re.sub(
        re.escape(INDEX_START) + r".*?" + re.escape(INDEX_END),
        block,
        text,
        flags=re.DOTALL,
    )
    readme_path.write_text(new_text)


def main():
    parser = argparse.ArgumentParser(description="Run daily digest")
    parser.add_argument("--topics", default="AI,Python,LangGraph")
    parser.add_argument("--db", default="digest.db")
    parser.add_argument("--output", default="digests")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    os.environ["DATABASE_PATH"] = args.db

    from yamlgraph.compile.graph_loader import load_and_compile

    graph = load_and_compile(str(REPO_DIR / "graph.yaml"))
    compiled = graph.compile()

    topics = [t.strip() for t in args.topics.split(",")]
    today = date.today().isoformat()
    result = compiled.invoke({"topics": topics, "today": today})

    print(f"✓ Found {len(result.get('raw_articles', []))} articles")
    print(f"✓ After filtering: {len(result.get('filtered_articles', []))}")

    bulletin = result.get("digest_markdown", "")
    # Guard: with zero new articles the ranker's output is untrusted
    if not result.get("filtered_articles") or not bulletin.strip():
        print("digest: no-op — no new stories, nothing to commit")
        return

    if args.dry_run:
        print("\n--- Bulletin (dry run) ---")
        print(bulletin)
        return

    output_dir = REPO_DIR / args.output
    output_dir.mkdir(exist_ok=True)
    bulletin_path = output_dir / f"{today}.md"
    bulletin_path.write_text(bulletin)
    update_readme_index(REPO_DIR / "README.md", output_dir)
    print(f"✓ Wrote {bulletin_path.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    main()
