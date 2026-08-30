"""Hacker News + RSS collector — the original digest source (FR-904).

Bound to the pipeline's `collect` slot by `hn_rss.tool.yaml`. Behaviour is
preserved exactly from the former `nodes/sources.py`; what changed is
ownership. The HN endpoint and the feed list live *here*, in the file the
manifest points at, so swapping sources swaps files instead of editing a
shared module that every digest inherits.

Transports are injectable so the collector ABI can be tested as a
signature rather than asserted as prose.
"""

import logging
from datetime import datetime
from time import struct_time

import feedparser
import httpx

logger = logging.getLogger(__name__)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
RSS_FEEDS = [
    "https://lobste.rs/rss",
    "https://dev.to/feed",
]
HN_LIMIT = 30
RSS_LIMIT = 20
TOTAL_LIMIT = 50


def _fetch_hn_story(story_id: int, http_get) -> dict | None:
    """Fetch a single HN story by ID."""
    try:
        data = http_get(f"{HN_API_BASE}/item/{story_id}.json", timeout=5).json()

        if not data or data.get("type") != "story":
            return None

        # Discussion link when the story has no external URL.
        url = data.get("url") or f"https://news.ycombinator.com/item?id={story_id}"

        return {
            "title": data.get("title", ""),
            "url": url,
            "source": "HN",
            "timestamp": datetime.fromtimestamp(data.get("time", 0)).isoformat(),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch HN story {story_id}: {e}")
        return None


def _fetch_hn(limit: int, http_get) -> list[dict]:
    """Fetch top stories from Hacker News."""
    try:
        story_ids = http_get(f"{HN_API_BASE}/topstories.json", timeout=10).json()[:limit]
    except Exception as e:
        logger.error(f"Failed to fetch HN top stories: {e}")
        return []

    stories = [s for sid in story_ids if (s := _fetch_hn_story(sid, http_get))]
    logger.info(f"📰 Fetched {len(stories)} stories from HN")
    return stories


def _fetch_rss(feeds: list[str], limit: int, rss_parse) -> list[dict]:
    """Fetch articles from RSS feeds."""
    articles = []

    for feed_url in feeds:
        try:
            for entry in rss_parse(feed_url).entries[:limit]:
                if getattr(entry, "published_parsed", None):
                    ts: struct_time = entry.published_parsed
                    timestamp = datetime(*ts[:6]).isoformat()
                else:
                    timestamp = datetime.now().isoformat()

                articles.append(
                    {
                        "title": entry.title,
                        "url": entry.link,
                        "source": "RSS",
                        "timestamp": timestamp,
                    }
                )
        except Exception as e:
            logger.warning(f"Failed to parse RSS feed {feed_url}: {e}")

    logger.info(f"📡 Fetched {len(articles)} articles from RSS")
    return articles[:limit]


def collect(config: dict | None = None, http_get=None, rss_parse=None) -> dict:
    """Collect articles from Hacker News and the RSS feed list.

    Returns:
        `{"raw_articles": [...]}` — each record carrying `title`, `url`,
        `source`, and `timestamp` (the frozen collector ABI).
    """
    http_get = http_get or httpx.get
    rss_parse = rss_parse or feedparser.parse

    articles = _fetch_hn(HN_LIMIT, http_get)
    articles.extend(_fetch_rss(RSS_FEEDS, RSS_LIMIT, rss_parse))

    logger.info(f"📊 Total articles: {len(articles[:TOTAL_LIMIT])}")
    return {"raw_articles": articles[:TOTAL_LIMIT]}
