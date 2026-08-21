"""Batch-integrity guard for the Haiku digest (Phase 4, test 4) plus the
budget typo-catcher (test 6's unit form).

The join is structural — index present / in range / unique, enum valid —
so unlike the Phase 3 regex-over-prose guard there is no false-positive
surface to tune. What it cannot check is summary faithfulness; that is a
documented open gap, not a missed assertion here.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agent.researcher import UsageSummary
from app.agent.trading.domain.errors import VendorError
from app.agent.trading.infrastructure import news_digest_port
from app.agent.trading.infrastructure.news_digest_port import (
    BATCH_SIZE,
    _assert_within_budget,
    _join,
    _parse_index,
    _render_batch,
    build_digest,
)


def _articles(n: int) -> list[dict]:
    return [
        {
            "headline": f"headline {i}",
            "_pub_date": date(2025, 3, 10),
            "source": "wire",
            "url": f"https://example.com/{i}",
            "summary": f"body {i}",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Test 4 — batch integrity
# ---------------------------------------------------------------------------

def test_join_flags_missing_duplicate_and_invalid_enum():
    articles = _articles(5)
    parsed = [
        {"index": 0, "summary": "s0", "sentiment": "positive"},
        {"index": 1, "summary": "s1", "sentiment": "negative"},
        {"index": 1, "summary": "s1 again", "sentiment": "positive"},   # duplicate
        {"index": 2, "summary": "s2", "sentiment": "bullish"},          # invalid enum
        {"index": 4, "summary": "s4", "sentiment": "neutral"},
        # index 3 missing entirely — data loss, must be visible
    ]

    items, issues = _join(articles, parsed)

    assert any("duplicate index 1" in i for i in issues)
    assert any("missing index 3" in i for i in issues)
    assert any("invalid sentiment 'bullish'" in i for i in issues)

    by_headline = {i.headline: i for i in items}
    assert set(by_headline) == {"headline 0", "headline 1", "headline 2", "headline 4"}
    # invalid enum degrades to neutral rather than being dropped or trusted
    assert by_headline["headline 2"].sentiment == "neutral"
    # the duplicate's first occurrence wins
    assert by_headline["headline 1"].summary == "s1"
    # no NewsItem carries metadata that isn't in the input set — the model
    # cannot introduce a headline, date, source, or URL
    input_headlines = {a["headline"] for a in articles}
    assert all(i.headline in input_headlines for i in items)
    assert all(i.published_date == date(2025, 3, 10) for i in items)


def test_bracketed_index_is_accepted_not_dropped():
    """Regression, from the first live run (FIG, 2026-08-21): Haiku returned
    "index": "[0]" for a 3-article batch — echoing the prompt's own [N]
    marker — and all three articles were dropped as unparseable. They were
    the most on-topic stories in the batch, so the cost of rejecting an
    unambiguous form is real article loss."""
    articles = _articles(3)
    parsed = [
        {"index": "[0]", "summary": "s0", "sentiment": "neutral"},
        {"index": "[1]", "summary": "s1", "sentiment": "positive"},
        {"index": " [2] ", "summary": "s2", "sentiment": "negative"},
    ]

    items, issues = _join(articles, parsed)

    assert issues == []
    assert [i.headline for i in items] == ["headline 0", "headline 1", "headline 2"]
    assert [i.sentiment for i in items] == ["neutral", "positive", "negative"]


def test_parse_index_accepts_unambiguous_forms_and_rejects_guesswork():
    assert _parse_index(3) == 3
    assert _parse_index("3") == 3
    assert _parse_index("[3]") == 3
    assert _parse_index(" [3] ") == 3
    assert _parse_index(3.0) == 3

    # a bool must not become index 1 via int(True); a non-integral float must
    # not silently truncate onto the wrong article
    with pytest.raises(ValueError):
        _parse_index(True)
    with pytest.raises(ValueError):
        _parse_index(1.7)
    with pytest.raises(ValueError):
        _parse_index("first")
    with pytest.raises(TypeError):
        _parse_index(None)


def test_join_flags_out_of_range_and_unparseable_indices():
    articles = _articles(2)
    parsed = [
        {"index": 0, "summary": "ok", "sentiment": "neutral"},
        {"index": 99, "summary": "phantom", "sentiment": "positive"},
        {"summary": "no index at all", "sentiment": "positive"},
        {"index": "one", "summary": "bad index", "sentiment": "positive"},
    ]

    items, issues = _join(articles, parsed)

    assert len(items) == 1
    assert any("out of range" in i for i in issues)
    assert sum("unparseable index" in i for i in issues) == 2
    assert any("missing index 1" in i for i in issues)


def test_render_batch_numbers_articles_and_truncates_bodies():
    articles = _articles(2)
    articles[1]["summary"] = "x" * 2000
    rendered = _render_batch(articles)
    assert "[0] HEADLINE: headline 0" in rendered
    assert "[1] HEADLINE: headline 1" in rendered
    assert "x" * 600 in rendered
    assert "x" * 601 not in rendered


# ---------------------------------------------------------------------------
# build_digest orchestration (LLM monkeypatched)
# ---------------------------------------------------------------------------

def _fake_usage(in_tok: int = 100, out_tok: int = 50):
    class _U:
        input_tokens = in_tok
        output_tokens = out_tok
        cache_creation_input_tokens = 0
        cache_read_input_tokens = 0
    return _U()


@pytest.mark.anyio
async def test_build_digest_batches_and_logs_cost_once(monkeypatch):
    articles = _articles(BATCH_SIZE + 3)   # forces exactly two batches
    batch_sizes: list[int] = []
    log_calls: list[tuple] = []

    async def fake_summarize(client, batch):
        batch_sizes.append(len(batch))
        return (
            [{"index": i, "summary": f"s{i}", "sentiment": "neutral"} for i in range(len(batch))],
            _fake_usage(),
        )

    def fake_log_cost(ticker, mode, usage):
        log_calls.append((ticker, mode, usage.input_tokens, usage.output_tokens))
        return 0.0123

    monkeypatch.setattr(news_digest_port, "_summarize_batch", fake_summarize)
    monkeypatch.setattr(news_digest_port, "log_cost", fake_log_cost)

    items, issues, cost = await build_digest(articles, "ACN")

    assert batch_sizes == [BATCH_SIZE, 3]
    assert len(items) == BATCH_SIZE + 3
    assert issues == []
    # one summed log line per run, not one per batch
    assert log_calls == [("ACN", "trading-news", 200, 100)]
    assert cost == 0.0123


@pytest.mark.anyio
async def test_build_digest_empty_input_skips_llm_entirely(monkeypatch):
    async def explode(client, batch):
        raise AssertionError("LLM called for an empty article list")

    monkeypatch.setattr(news_digest_port, "_summarize_batch", explode)

    items, issues, cost = await build_digest([], "ACN")

    assert items == [] and issues == [] and cost is None


# ---------------------------------------------------------------------------
# Test 6 (unit form) — budget typo-catcher
# ---------------------------------------------------------------------------

def test_budget_guard_trips_over_threshold_and_passes_under_it():
    _assert_within_budget(None)      # pricing unconfigured: nothing to check
    _assert_within_budget(0.02)      # a normal run, ~10x under
    with pytest.raises(AssertionError, match="exceeds"):
        _assert_within_budget(0.50)  # a Haiku run cannot cost this — wrong model
