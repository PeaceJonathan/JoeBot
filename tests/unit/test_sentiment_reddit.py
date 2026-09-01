"""Unit tests for joebot.signals.sentiment_reddit scoring logic, against
fixture mention data injected via monkeypatch -- no network access."""
import datetime as dt

import pytest

from joebot.data import reddit_client
from joebot.signals.sentiment_reddit import SentimentRedditSignal

AS_OF = dt.date(2026, 6, 1)


def _mention(days_ago, subreddit="stocks"):
    return {
        "subreddit": subreddit,
        "created_date": (AS_OF - dt.timedelta(days=days_ago)).isoformat(),
        "title": "test post",
        "score": 10,
    }


def test_no_mentions_scores_zero_low_confidence(monkeypatch):
    monkeypatch.setattr(reddit_client, "fetch_mentions", lambda *a, **k: [])
    result = SentimentRedditSignal().score("TEST", AS_OF)
    assert result.score == 0.0
    assert result.confidence == pytest.approx(0.3)


def test_high_volume_high_velocity_scores_high(monkeypatch):
    # 20 mentions, all in the most recent half of a 14-day window -> max
    # volume score, high velocity score (nothing in the earlier half).
    mentions = [_mention(days_ago=d) for d in range(0, 6)] * 4  # 24 recent mentions
    monkeypatch.setattr(reddit_client, "fetch_mentions", lambda *a, **k: mentions)
    result = SentimentRedditSignal(lookback_days=14).score("TEST", AS_OF)
    assert result.score > 0.7
    assert result.metadata["mention_count"] == len(mentions)


def test_flat_mention_rate_scores_moderate_not_high(monkeypatch):
    # Same count recent vs earlier -> velocity_ratio == 1.0 -> velocity_score 0
    mentions = [_mention(days_ago=1), _mention(days_ago=2), _mention(days_ago=10), _mention(days_ago=12)]
    monkeypatch.setattr(reddit_client, "fetch_mentions", lambda *a, **k: mentions)
    result = SentimentRedditSignal(lookback_days=14).score("TEST", AS_OF)
    assert result.metadata["velocity_ratio"] == pytest.approx(1.0)
    # volume_score = 4/20 = 0.2, velocity_score = 0 -> total = 0.1
    assert result.score == pytest.approx(0.1, abs=1e-6)
