"""Reddit mention data via PRAW (the official Reddit API), for the
sentiment signal in joebot/signals/sentiment_reddit.py.

Reddit's free tier is ~100 queries/min per OAuth client for non-commercial
personal use, which is what this project is -- stay within the official
API, don't scrape beyond it. If REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET
aren't configured (see .env.example), this gracefully returns no mentions
rather than raising, consistent with every other data source's
graceful-degradation pattern in this project.

NOTE: like the Phase 2 SEC filing feeds, this hasn't been exercised against
a live Reddit API call from this development environment (no network
access to reddit.com either). PRAW's public interface (Reddit(...),
.subreddit(...).search(...)) is stable and well-documented, so this is
lower-risk than the edgartools attribute-name guessing in sec_client.py,
but it still needs a real smoke test with real credentials before trusting
its output.
"""
from __future__ import annotations

import datetime as dt
import logging

from config import settings
from joebot.data.cache import DiskCache

log = logging.getLogger(__name__)

_mentions_cache = DiskCache(namespace="reddit_mentions", ttl_seconds=6 * 3600)

DEFAULT_SUBREDDITS = ("stocks", "pennystocks", "wallstreetbets", "smallstreetbets")
MAX_RESULTS_PER_SUBREDDIT = 50

_client = None
_client_init_attempted = False


def _get_client():
    global _client, _client_init_attempted
    if _client_init_attempted:
        return _client
    _client_init_attempted = True

    if not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
        log.info("Reddit credentials not configured -- sentiment_reddit signal will score 0 for everything.")
        return None

    try:
        import praw

        _client = praw.Reddit(
            client_id=settings.REDDIT_CLIENT_ID,
            client_secret=settings.REDDIT_CLIENT_SECRET,
            user_agent=settings.REDDIT_USER_AGENT,
        )
    except Exception as exc:
        log.warning("Failed to initialize Reddit client: %s", exc)
        _client = None

    return _client


def fetch_mentions(
    ticker: str,
    as_of_date: dt.date,
    lookback_days: int = 14,
    subreddits: tuple[str, ...] = DEFAULT_SUBREDDITS,
) -> list[dict]:
    """List of {"subreddit", "created_date" (ISO), "title", "score"} dicts,
    point-in-time gated to [as_of_date - lookback_days, as_of_date].
    Returns [] if Reddit isn't configured or the API call fails.
    """
    cache_key = f"{ticker}_{lookback_days}"
    cached = _mentions_cache.get(cache_key)
    if cached is None:
        cached = _fetch_mentions_uncached(ticker, subreddits)
        _mentions_cache.set(cache_key, cached)

    cutoff = as_of_date - dt.timedelta(days=lookback_days)
    return [m for m in cached if cutoff <= dt.date.fromisoformat(m["created_date"]) <= as_of_date]


def _fetch_mentions_uncached(ticker: str, subreddits: tuple[str, ...]) -> list[dict]:
    client = _get_client()
    if client is None:
        return []

    results = []
    try:
        for sub_name in subreddits:
            subreddit = client.subreddit(sub_name)
            for submission in subreddit.search(ticker, time_filter="month", limit=MAX_RESULTS_PER_SUBREDDIT):
                created = dt.datetime.utcfromtimestamp(submission.created_utc).date()
                results.append({
                    "subreddit": sub_name,
                    "created_date": created.isoformat(),
                    "title": submission.title,
                    "score": submission.score,
                })
    except Exception as exc:
        log.warning("Reddit mention fetch failed for %s: %s", ticker, exc)
        return []

    return results
