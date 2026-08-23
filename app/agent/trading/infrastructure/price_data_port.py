from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import finnhub
import pandas as pd
import yfinance as yf

from app.agent.trading.domain.errors import VendorError

MIN_BARS_REQUIRED = 210   # 200-day SMA + small buffer for weekends/holidays


async def get_price_history(ticker: str) -> tuple[pd.DataFrame, str, int]:
    """Returns (OHLCV DataFrame, source_name, bars_dropped_invalid).

    Raises VendorError if both vendors fail or return insufficient history.
    Bars with a missing Close or Volume are dropped here, at the vendor
    boundary, so every downstream consumer sees the same clean frame and
    `bars_used` counts what was actually computed on. See _drop_invalid_bars.
    """
    df, source = await asyncio.to_thread(_try_yfinance, ticker)
    if df is None or len(_drop_invalid_bars(df)[0]) < MIN_BARS_REQUIRED:
        df, source = await asyncio.to_thread(_try_finnhub, ticker)

    if df is None:
        raise VendorError(f"No price data for {ticker} from yfinance or Finnhub")

    # Cleaned before the sufficiency check, not after: a frame padded out to
    # MIN_BARS_REQUIRED with unusable rows does not have enough history for a
    # 200-day SMA, and passing it through would just move the failure.
    df, dropped = _drop_invalid_bars(df)

    if len(df) < MIN_BARS_REQUIRED:
        raise VendorError(
            f"{ticker}: only {len(df)} usable bars from {source} "
            f"({dropped} dropped as incomplete), need {MIN_BARS_REQUIRED} for "
            f"200-day SMA (recent IPO or thin ticker?)"
        )
    return df, source, dropped


def _drop_invalid_bars(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop rows with a missing Close or Volume, and report how many.

    Not defensive housekeeping — a single bad bar silently destroyed a whole
    indicator in production. yfinance returned MSFT with a NaN Close on bar 0
    (2025-08-21); MACD is built on exponential moving averages, which seed
    from the first observation and propagate NaN forward, so all 251
    subsequent rows came back NaN while SMA and RSI were unaffected (their
    trailing windows never reach bar 0). The memo reported "MACD data is
    unavailable" and no one could see why. With the bar dropped the same run
    yields MACD 20.02 / signal 23.25 / histogram -3.23 — a bearish crossover
    that had been invisible.

    Dropping rather than interpolating is deliberate: an interpolated bar is
    a number the vendor never published, and this pipeline reports figures it
    can trace. A dropped bar is a gap; an invented one is a fabrication.

    Volume is included because volume_vs_20d_avg divides by a 20-bar mean —
    a NaN there yields NaN, which is a valid float to pydantic and would
    reach the report as `NaN`, and JSON has no such literal.
    """
    required = [c for c in ("Close", "Volume") if c in df.columns]
    if not required:
        return df, 0
    clean = df.dropna(subset=required)
    return clean, len(df) - len(clean)


def _try_yfinance(ticker: str) -> tuple[pd.DataFrame | None, str]:
    try:
        df = yf.Ticker(ticker).history(period="1y", interval="1d")
        if df is None or df.empty:
            return None, "yfinance"
        return df, "yfinance"
    except Exception:
        return None, "yfinance"


def _try_finnhub(ticker: str) -> tuple[pd.DataFrame | None, str]:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return None, "finnhub"
    try:
        client = finnhub.Client(api_key=api_key)
        to_ts = int(datetime.now(timezone.utc).timestamp())
        from_ts = to_ts - 400 * 24 * 60 * 60  # ~400 calendar days back
        candles = client.stock_candles(ticker, "D", from_ts, to_ts)
        if candles.get("s") != "ok":
            return None, "finnhub"
        df = pd.DataFrame(
            {
                "Open": candles["o"],
                "High": candles["h"],
                "Low": candles["l"],
                "Close": candles["c"],
                "Volume": candles["v"],
            },
            index=pd.to_datetime(candles["t"], unit="s"),
        )
        return df, "finnhub"
    except Exception:
        return None, "finnhub"
