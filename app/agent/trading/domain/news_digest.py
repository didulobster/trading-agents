from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

Sentiment = Literal["positive", "negative", "neutral"]


class NewsItem(BaseModel):
    """One article. Every field except `summary`/`sentiment` is carried
    through verbatim from the vendor payload — the LLM never retypes them."""

    headline: str
    published_date: date        # UTC date, derived in Python from the unix ts
    source: str
    url: str
    summary: str                # LLM-generated, one line
    sentiment: Sentiment        # LLM-generated, enum-constrained


class NewsDigest(BaseModel):
    ticker: str
    as_of_date: date            # the probe/analysis date — the upper bound
    window_start: date          # as_of_date - lookback_days
    items: list[NewsItem]

    # Provenance / audit fields. These exist so the digest can be
    # inspected without re-running the fetch.
    raw_article_count: int      # what the vendor returned
    deduped_count: int          # after dedup + window filter
    dropped_out_of_window: int  # articles the Python-side date filter rejected
    dropped_missing_date: int
    truncated_by_cap: bool      # did MAX_ARTICLES bite?
    data_source: str = "finnhub"


class SentimentSummary(BaseModel):
    """Deterministic aggregate over NewsDigest.items — no LLM."""

    ticker: str
    as_of_date: date
    positive: int
    negative: int
    neutral: int
    net_score: float            # (pos - neg) / total, 0.0 when total == 0
    article_count: int
