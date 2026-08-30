"""arXiv cs.AI collector — the second binding (FR-904).

Bound to the pipeline's `collect` slot by `arxiv.tool.yaml`. This exists
to falsify the slot: a slot with one binding is an inline tool with extra
ceremony. arXiv is a genuinely different source from HN/RSS tech news —
academic preprints, a different cadence, a different relevance profile —
and it needs no new dependency, since the Atom feed parses with the
`feedparser` already installed for RSS.

Nothing downstream of collection changes. Filtering, extraction,
analysis, ranking, rendering, and delivery are shared verbatim.
"""

import logging
from datetime import datetime
from time import struct_time

import feedparser

logger = logging.getLogger(__name__)

ARXIV_FEED = "http://export.arxiv.org/api/query"
ARXIV_CATEGORY = "cs.AI"
ARXIV_LIMIT = 50


def _feed_url(category: str, limit: int) -> str:
    return (
        f"{ARXIV_FEED}?search_query=cat:{category}"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={limit}"
    )


def collect(config: dict | None = None, feed_parse=None) -> dict:
    """Collect recent arXiv submissions in the configured category.

    Returns:
        `{"raw_articles": [...]}` — each record carrying `title`, `url`,
        `source`, and `timestamp` (the frozen collector ABI).
    """
    feed_parse = feed_parse or feedparser.parse
    articles = []

    try:
        entries = feed_parse(_feed_url(ARXIV_CATEGORY, ARXIV_LIMIT)).entries
    except Exception as e:
        logger.error(f"Failed to fetch arXiv {ARXIV_CATEGORY}: {e}")
        return {"raw_articles": []}

    for entry in entries[:ARXIV_LIMIT]:
        if getattr(entry, "published_parsed", None):
            ts: struct_time = entry.published_parsed
            timestamp = datetime(*ts[:6]).isoformat()
        else:
            timestamp = datetime.now().isoformat()

        articles.append(
            {
                # arXiv wraps titles across lines; the renderer wants one.
                "title": " ".join(entry.title.split()),
                "url": entry.link,
                "source": "arXiv",
                "timestamp": timestamp,
            }
        )

    logger.info(f"🔬 Fetched {len(articles)} preprints from arXiv {ARXIV_CATEGORY}")
    return {"raw_articles": articles}
