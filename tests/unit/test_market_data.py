"""Unit tests for joebot.data.market_data's rate-limit retry logic.

Regression coverage for a real issue reported after running the app
against live Yahoo Finance data: scanning a full sector universe (dozens
of tickers x several yfinance calls each) hit HTTP 429s partway through,
and every ticker after that silently vanished from the results with no
visible explanation (each just failed and was dropped by
joebot/screener/sector_screens.py's per-ticker exception handling). Retry
with backoff on yfinance's own YFRateLimitError (confirmed by reading
yfinance/data.py's source -- it's raised specifically on a 429, not other
failures) is the fix; these tests cover the retry helper's actual behavior
without needing real network access or real waiting.
"""
from __future__ import annotations

from unittest import mock

import pytest
from yfinance.exceptions import YFRateLimitError

from joebot.data.market_data import _call_with_rate_limit_retry


def test_succeeds_immediately_without_retrying():
    fn = mock.Mock(return_value="ok")
    with mock.patch("joebot.data.market_data.time.sleep") as sleep:
        result = _call_with_rate_limit_retry(fn)
    assert result == "ok"
    assert fn.call_count == 1
    sleep.assert_not_called()


def test_retries_after_a_rate_limit_error_then_succeeds():
    fn = mock.Mock(side_effect=[YFRateLimitError(), "ok"])
    with mock.patch("joebot.data.market_data.time.sleep") as sleep:
        result = _call_with_rate_limit_retry(fn)
    assert result == "ok"
    assert fn.call_count == 2
    sleep.assert_called_once()


def test_gives_up_after_exhausting_all_retries_and_reraises():
    fn = mock.Mock(side_effect=YFRateLimitError())
    with mock.patch("joebot.data.market_data.time.sleep"):
        with pytest.raises(YFRateLimitError):
            _call_with_rate_limit_retry(fn)
    # 1 initial attempt + len(_RATE_LIMIT_RETRY_DELAYS) retries
    from joebot.data.market_data import _RATE_LIMIT_RETRY_DELAYS
    assert fn.call_count == 1 + len(_RATE_LIMIT_RETRY_DELAYS)


def test_non_rate_limit_error_propagates_immediately_without_retry():
    fn = mock.Mock(side_effect=ValueError("some other failure"))
    with mock.patch("joebot.data.market_data.time.sleep") as sleep:
        with pytest.raises(ValueError):
            _call_with_rate_limit_retry(fn)
    assert fn.call_count == 1
    sleep.assert_not_called()
