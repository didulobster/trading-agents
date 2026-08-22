from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.agent.trading.domain.errors import VendorError

FINNHUB_URL = "https://finnhub.io/api/v1/company-news"
DEFAULT_LOOKBACK_DAYS = 14
# Sized to cover a full lookback window rather than to be a cost floor.
#
# At 60 this cap, not the budget, was the binding constraint, and it was
# discarding the evidence: of MSFT's 247 in-window articles on 2026-08-21,
# 58 were primarily about Microsoft and the cap kept 6 of them — the newest
# 60 articles spanned only 5 days of a 14-day window, dropping an entire
# 101-article event day. Relevance filtering made the signal correct but
# left it too thin to use.
#
# 300 is derived from the per-run budget, not chosen for roundness. Worst
# case per article is ~$0.00042 (a headline plus a 600-char body in, an
# index, a <=25-word summary and two enums out), plus a 496-token system
# prompt per batch of BATCH_SIZE. At 300 that is ~$0.136, about 68% of
# NEWS_BUDGET_USD, so a full-cap run cannot trip the budget assertion —
# volume degrades to flagged truncation instead of an exception raised
# after the money is already spent. Measured cost tracks the estimate
# closely: $0.000403/article on a real 60-article AVGO run.
MAX_ARTICLES = 300
REQUEST_TIMEOUT = 20.0


async def fetch_company_news(
    ticker: str,
    as_of_date: date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[list[dict[str, Any]], date]:
    """Fetch raw Finnhub articles bounded to [as_of - lookback, as_of].

    Returns (raw_articles, window_start). Bounds are NOT optional — there is
    no code path here that fetches without them.
    """
    window_start = as_of_date - timedelta(days=lookback_days)
    token = os.environ.get("FINNHUB_API_KEY")
    if not token:
        raise VendorError("FINNHUB_API_KEY not set")

    params = {
        "symbol": ticker.upper(),
        "from": window_start.isoformat(),
        "to": as_of_date.isoformat(),
        "token": token,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(FINNHUB_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPStatusError as e:
        raise VendorError(
            f"Finnhub company-news HTTP {e.response.status_code} for {ticker}"
        ) from e
    except (httpx.HTTPError, ValueError) as e:
        raise VendorError(f"Finnhub company-news failed for {ticker}: {e}") from e

    if not isinstance(payload, list):
        raise VendorError(
            f"Finnhub returned {type(payload).__name__}, expected list — "
            f"likely a rate-limit or auth error body"
        )

    return payload, window_start


def _to_utc_date(ts: int | float | None) -> date | None:
    """Convert Finnhub's unix ts to a UTC calendar date.

    CRITICAL: tz=timezone.utc is not optional. datetime.fromtimestamp(ts)
    without tzinfo uses the *machine's* local timezone. On a UTC+8 box
    (Singapore), an article published 2025-03-01T20:00Z becomes
    2025-03-02 local — it fails an as_of=2025-03-01 filter and gets dropped,
    or slips through in the mirror case. The digest would then differ
    depending on which machine ran the pipeline. Deterministic in UTC only.

    `if not ts` also catches ts == 0: Finnhub occasionally emits a zero
    timestamp, and fromtimestamp(0).date() is 1970-01-01, which would pass
    a `<= as_of_date` check silently. Counted in dropped_missing_date.
    """
    if not ts:            # covers None AND 0
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).date()


def filter_and_dedup(
    raw: list[dict[str, Any]],
    as_of_date: date,
    window_start: date,
) -> tuple[list[dict[str, Any]], int, int, bool]:
    """Re-apply the window bounds in Python — never trust the vendor's
    from/to. An out-of-window article is a silent correctness failure, and
    the exit criterion is about the digest, not about Finnhub's honesty.

    Returns (clean_articles, dropped_out_of_window, dropped_missing_date, truncated).
    """
    dropped_window = 0
    dropped_missing = 0
    seen: set[tuple[str, date]] = set()
    clean: list[dict[str, Any]] = []

    for art in raw:
        pub = _to_utc_date(art.get("datetime"))
        if pub is None:
            dropped_missing += 1
            continue
        if pub > as_of_date or pub < window_start:
            dropped_window += 1
            continue

        # Dedup: syndicated reprints share a headline across sources.
        key = (" ".join(art.get("headline", "").lower().split()), pub)
        if not key[0] or key in seen:
            continue
        seen.add(key)

        art["_pub_date"] = pub          # normalized, trusted downstream
        clean.append(art)

    # Newest first, then cap. Cap AFTER sorting so truncation drops the
    # oldest, not an arbitrary slice.
    clean.sort(key=lambda a: a["_pub_date"], reverse=True)
    truncated = len(clean) > MAX_ARTICLES
    return clean[:MAX_ARTICLES], dropped_window, dropped_missing, truncated
