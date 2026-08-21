"""news_node wiring: the as_of guard, the empty-window case (a valid
result, not an error), and the lookahead post-assertion.

Network and LLM are monkeypatched at the nodes-module seam — the same
names news_node actually calls — so these tests exercise the real node
body, not a reimplementation of it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import app.agent.trading.application.nodes as nodes
from app.agent.trading.domain.news_digest import NewsDigest, NewsItem

AS_OF = date(2025, 3, 15)


def _item(pub: date, sentiment: str = "neutral") -> NewsItem:
    return NewsItem(
        headline=f"story on {pub}",
        published_date=pub,
        source="wire",
        url="https://example.com/x",
        summary="one line",
        sentiment=sentiment,
    )


def _patch_ports(monkeypatch, raw, items, issues=None, cost=0.01):
    async def fake_fetch(ticker, as_of, lookback_days=14):
        return raw, as_of - timedelta(days=lookback_days)

    async def fake_digest(articles, ticker):
        return items, issues or [], cost

    monkeypatch.setattr(nodes, "fetch_company_news", fake_fetch)
    monkeypatch.setattr(nodes, "build_digest", fake_digest)


@pytest.mark.anyio
async def test_news_node_refuses_to_run_without_as_of_date():
    with pytest.raises(ValueError, match="as_of_date missing"):
        await nodes.news_node({"ticker": "ACN"})


# ---------------------------------------------------------------------------
# Test 5 — empty result is a valid result
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_quiet_ticker_yields_empty_digest_without_error(monkeypatch):
    _patch_ports(monkeypatch, raw=[], items=[], cost=None)

    update = await nodes.news_node({"ticker": "ACN", "as_of_date": AS_OF})

    digest = update["news_digest"]
    assert isinstance(digest, NewsDigest)
    assert digest.items == []
    assert digest.raw_article_count == 0
    assert digest.as_of_date == AS_OF
    assert update["news_digest_issues"] == []


@pytest.mark.anyio
async def test_news_node_builds_digest_with_provenance_counts(monkeypatch):
    raw = [
        {"headline": "kept", "datetime": 1741780800, "source": "wire",
         "url": "https://example.com/1", "summary": "b"},
        {"headline": "late", "datetime": 1750000000, "source": "wire",
         "url": "https://example.com/2", "summary": "b"},
        {"headline": "no ts", "datetime": 0, "source": "wire",
         "url": "https://example.com/3", "summary": "b"},
    ]
    _patch_ports(monkeypatch, raw=raw, items=[_item(date(2025, 3, 12), "positive")],
                 issues=["missing index 9"])

    update = await nodes.news_node({"ticker": "ACN", "as_of_date": AS_OF})

    digest = update["news_digest"]
    assert digest.raw_article_count == 3
    # the real filter_and_dedup ran: one in-window, one late, one zero-ts
    assert digest.deduped_count == 1
    assert digest.dropped_out_of_window == 1
    assert digest.dropped_missing_date == 1
    assert digest.truncated_by_cap is False
    assert update["news_digest_issues"] == ["missing index 9"]


# ---------------------------------------------------------------------------
# Lookahead post-assertion
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_post_dated_item_in_digest_raises_lookahead_leak(monkeypatch):
    _patch_ports(
        monkeypatch,
        raw=[],
        items=[_item(AS_OF), _item(AS_OF + timedelta(days=2))],
    )

    with pytest.raises(AssertionError, match="Lookahead leak"):
        await nodes.news_node({"ticker": "ACN", "as_of_date": AS_OF})


# ---------------------------------------------------------------------------
# sentiment_node — deterministic aggregation, no LLM
# ---------------------------------------------------------------------------

def _digest(items: list[NewsItem]) -> NewsDigest:
    return NewsDigest(
        ticker="ACN",
        as_of_date=AS_OF,
        window_start=AS_OF - timedelta(days=14),
        items=items,
        raw_article_count=len(items),
        deduped_count=len(items),
        dropped_out_of_window=0,
        dropped_missing_date=0,
        truncated_by_cap=False,
    )


@pytest.mark.anyio
async def test_sentiment_node_aggregates_counts_and_net_score():
    items = [
        _item(AS_OF, "positive"),
        _item(AS_OF - timedelta(days=1), "positive"),
        _item(AS_OF - timedelta(days=2), "positive"),
        _item(AS_OF - timedelta(days=3), "negative"),
        _item(AS_OF - timedelta(days=4), "neutral"),
    ]

    update = await nodes.sentiment_node({"news_digest": _digest(items)})

    s = update["sentiment_summary"]
    assert (s.positive, s.negative, s.neutral) == (3, 1, 1)
    assert s.article_count == 5
    assert s.net_score == pytest.approx((3 - 1) / 5)
    assert s.ticker == "ACN" and s.as_of_date == AS_OF


@pytest.mark.anyio
async def test_sentiment_node_handles_empty_digest_as_valid():
    """Test 5's second half: absence of news is a valid result. net_score
    is 0.0 with article_count 0 — not neutrality-with-evidence."""
    update = await nodes.sentiment_node({"news_digest": _digest([])})

    s = update["sentiment_summary"]
    assert s.article_count == 0
    assert s.net_score == 0.0
    assert (s.positive, s.negative, s.neutral) == (0, 0, 0)
