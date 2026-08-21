"""Point-in-time correctness of the news filter — the Phase 4 headline
exit criterion, tested against planted violations rather than a live API.

A live-API test here is close to worthless: if Finnhub honours `to`
correctly, the response contains no post-date articles, the filter has
nothing to reject, and the test passes without exercising the code path
under test. A green test that proves nothing retires the concern falsely,
so every fixture below plants the violation explicitly.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone

import pytest

from app.agent.trading.infrastructure.news_data_port import (
    MAX_ARTICLES,
    _to_utc_date,
    filter_and_dedup,
)

AS_OF = date(2025, 3, 15)
WINDOW_START = date(2025, 3, 1)


def _art(headline: str, dt: datetime | None, source: str = "wire") -> dict:
    return {
        "headline": headline,
        "datetime": int(dt.timestamp()) if dt is not None else None,
        "source": source,
        "url": f"https://example.com/{abs(hash(headline))}",
        "summary": f"body of {headline}",
    }


# ---------------------------------------------------------------------------
# Test 1 — point-in-time filter
# ---------------------------------------------------------------------------

def test_articles_after_probe_date_are_dropped():
    raw = [
        _art("in window",       datetime(2025, 3, 10, tzinfo=timezone.utc)),
        # 23:30 UTC on the probe date — `to` is inclusive of the day, and an
        # over-strict filter that drops it silently loses the most recent
        # (most decision-relevant) article.
        _art("on the boundary", datetime(2025, 3, 15, 23, 30, tzinfo=timezone.utc)),
        _art("ONE DAY LATE",    datetime(2025, 3, 16, 0, 1, tzinfo=timezone.utc)),
        _art("WAY LATE",        datetime(2025, 6, 1, tzinfo=timezone.utc)),
        _art("before window",   datetime(2025, 2, 20, tzinfo=timezone.utc)),
    ]
    clean, dropped_win, dropped_missing, truncated = filter_and_dedup(
        raw, AS_OF, WINDOW_START
    )

    headlines = {a["headline"] for a in clean}
    assert headlines == {"in window", "on the boundary"}
    assert dropped_win == 3
    assert dropped_missing == 0
    assert truncated is False
    assert all(a["_pub_date"] <= AS_OF for a in clean)


# ---------------------------------------------------------------------------
# Test 2 — timezone determinism
# ---------------------------------------------------------------------------

# The 16:00–23:59 UTC band is where UTC+8 rolls to the next local day —
# without an article in that band the cross-TZ comparison passes vacuously.
RAW_TZ_FIXTURE = [
    _art("evening utc in window",  datetime(2025, 3, 15, 20, 0, tzinfo=timezone.utc)),
    _art("evening utc late",       datetime(2025, 3, 16, 20, 0, tzinfo=timezone.utc)),
    _art("morning utc in window",  datetime(2025, 3, 10, 9, 0, tzinfo=timezone.utc)),
    _art("window edge evening",    datetime(2025, 2, 28, 22, 0, tzinfo=timezone.utc)),
]


def test_filter_is_timezone_independent():
    """Same input must yield the same digest regardless of machine TZ."""
    original_tz = os.environ.get("TZ")
    results = []
    try:
        for tz in ("UTC", "Asia/Singapore", "America/Los_Angeles"):
            os.environ["TZ"] = tz
            time.tzset()
            clean, *_ = filter_and_dedup(
                [dict(a) for a in RAW_TZ_FIXTURE], AS_OF, WINDOW_START
            )
            results.append({a["headline"] for a in clean})
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()

    assert results[0] == results[1] == results[2]
    assert results[0] == {"evening utc in window", "morning utc in window"}


# ---------------------------------------------------------------------------
# Test 3 — missing/zero timestamp
# ---------------------------------------------------------------------------

def test_zero_or_missing_timestamp_is_dropped_not_dated_1970():
    raw = [
        _art("valid", datetime(2025, 3, 12, tzinfo=timezone.utc)),
        {**_art("zero ts", None), "datetime": 0},
        _art("missing ts", None),
    ]
    clean, dropped_win, dropped_missing, _ = filter_and_dedup(raw, AS_OF, WINDOW_START)

    assert {a["headline"] for a in clean} == {"valid"}
    assert dropped_missing == 2
    assert dropped_win == 0
    assert all(a["_pub_date"].year != 1970 for a in clean)


def test_to_utc_date_treats_zero_as_missing():
    assert _to_utc_date(0) is None
    assert _to_utc_date(None) is None
    # sanity: a real timestamp converts on the UTC calendar
    assert _to_utc_date(
        datetime(2025, 3, 15, 23, 59, tzinfo=timezone.utc).timestamp()
    ) == date(2025, 3, 15)


# ---------------------------------------------------------------------------
# Dedup + cap behaviour
# ---------------------------------------------------------------------------

def test_syndicated_reprints_dedup_on_normalized_headline_and_date():
    dt = datetime(2025, 3, 10, tzinfo=timezone.utc)
    raw = [
        _art("Acme beats estimates", dt, source="reuters"),
        {**_art("ACME  beats   Estimates", dt, source="yahoo"), "headline": "ACME  beats   Estimates"},
        # same headline on a different day is a different story, kept
        _art("Acme beats estimates", datetime(2025, 3, 11, tzinfo=timezone.utc)),
        # empty headline is dropped
        {**_art("", dt), "headline": ""},
    ]
    clean, *_ = filter_and_dedup(raw, AS_OF, WINDOW_START)

    assert len(clean) == 2
    assert {a["_pub_date"] for a in clean} == {date(2025, 3, 10), date(2025, 3, 11)}


def test_cap_truncates_oldest_after_newest_first_sort():
    raw = [
        _art(f"story {i}", datetime(2025, 3, 1 + (i % 14), tzinfo=timezone.utc))
        for i in range(MAX_ARTICLES + 10)
    ]
    clean, _, _, truncated = filter_and_dedup(raw, AS_OF, WINDOW_START)

    assert truncated is True
    assert len(clean) == MAX_ARTICLES
    dates = [a["_pub_date"] for a in clean]
    assert dates == sorted(dates, reverse=True)
    # the dropped articles are the oldest, not an arbitrary slice
    kept_oldest = min(dates)
    all_dates = sorted(
        (_to_utc_date(a["datetime"]) for a in raw), reverse=True
    )
    assert kept_oldest >= all_dates[MAX_ARTICLES - 1]
