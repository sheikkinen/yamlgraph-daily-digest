"""Archive the bulletin to disk and refresh the README index (FR-903).

Runs before delivery: persist-before-publish. A send that fails after this
leaves a complete bulletin on disk and a red run, so the next run retries
the day cleanly.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_DIR = Path(__file__).parent.parent
INDEX_START = "<!-- digest-index -->"
INDEX_END = "<!-- /digest-index -->"
INDEX_SIZE = 14


def update_readme_index(readme_path: Path, digests_dir: Path) -> None:
    """Rewrite the digest-index block with the latest bulletins."""
    bulletins = sorted(digests_dir.glob("*.md"), reverse=True)[:INDEX_SIZE]
    entries = "\n".join(f"- [{p.stem}]({digests_dir.name}/{p.name})" for p in bulletins)
    block = f"{INDEX_START}\n{entries}\n{INDEX_END}"
    text = readme_path.read_text()
    readme_path.write_text(
        re.sub(
            re.escape(INDEX_START) + r".*?" + re.escape(INDEX_END),
            block,
            text,
            flags=re.DOTALL,
        )
    )


def write_bulletin(
    today: str,
    digest_markdown: str,
    output_dir: str = "digests",
) -> dict:
    """Write digests/<today>.md and refresh the README index."""
    if not today:
        raise ValueError("write_bulletin: 'today' is required")
    if not digest_markdown.strip():
        raise ValueError(
            "write_bulletin: empty bulletin reached the archive node; "
            "the gate should have routed digest_status != ready to END"
        )

    target_dir = REPO_DIR / output_dir
    target_dir.mkdir(exist_ok=True)
    path = target_dir / f"{today}.md"
    path.write_text(digest_markdown)
    update_readme_index(REPO_DIR / "README.md", target_dir)

    logger.info("📄 Archived %s", path.relative_to(REPO_DIR))
    return {"path": str(path)}
