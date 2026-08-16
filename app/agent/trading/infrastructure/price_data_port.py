from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import finnhub
import pandas as pd
import yfinance as yf

from app.agent.trading.domain.errors import VendorError

MIN_BARS_REQUIRED = 210   # 200-day SMA + small buffer for weekends/holidays


async def get_price_history(ticker: str) -> tuple[pd.DataFrame, str]:
    """Returns (OHLCV DataFrame, source_name). Raises VendorError if both
    vendors fail or return insufficient history."""
    df, source = await asyncio.to_thread(_try_yfinance, ticker)
    if df is None or len(df) < MIN_BARS_REQUIRED:
        df, source = await asyncio.to_thread(_try_finnhub, ticker)

    if df is None:
        raise VendorError(f"No price data for {ticker} from yfinance or Finnhub")
    if len(df) < MIN_BARS_REQUIRED:
        raise VendorError(
            f"{ticker}: only {len(df)} bars available from {source}, "
            f"need {MIN_BARS_REQUIRED} for 200-day SMA (recent IPO or thin ticker?)"
        )
    return df, source


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
