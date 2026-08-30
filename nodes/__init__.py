"""Daily Digest node implementations (GitHub-native variant).

Collection is deliberately absent: it is an FR-904 tool slot, bound at
invocation from `sources/`. Everything here is shared by every binding.
"""

from .content import fetch_article_content
from .filters import filter_recent
from .formatting import format_markdown

__all__ = [
    "filter_recent",
    "fetch_article_content",
    "format_markdown",
]
