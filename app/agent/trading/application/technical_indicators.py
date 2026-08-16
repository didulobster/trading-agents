from __future__ import annotations

import pandas as pd
import pandas_ta_classic as ta

from app.agent.trading.domain.technical_report import TechnicalIndicators


def compute_indicators(df: pd.DataFrame) -> TechnicalIndicators:
    """Pure function: OHLCV DataFrame in, typed indicator values out.
    No network calls, no LLM calls — independently unit-testable with a fixture."""
    close = df["Close"]

    sma_50 = ta.sma(close, length=50)
    sma_200 = ta.sma(close, length=200)
    rsi_14 = ta.rsi(close, length=14)
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    bb_df = ta.bbands(close, length=20, std=2)

    volume_avg_20 = df["Volume"].tail(20).mean()
    last_volume = df["Volume"].iloc[-1]

    return TechnicalIndicators(
        sma_50=_last_valid(sma_50),
        sma_200=_last_valid(sma_200),
        rsi_14=_last_valid(rsi_14),
        macd=_last_valid(macd_df["MACD_12_26_9"]),
        macd_signal=_last_valid(macd_df["MACDs_12_26_9"]),
        macd_histogram=_last_valid(macd_df["MACDh_12_26_9"]),
        bb_upper=_last_valid(bb_df["BBU_20_2.0"]),
        bb_mid=_last_valid(bb_df["BBM_20_2.0"]),
        bb_lower=_last_valid(bb_df["BBL_20_2.0"]),
        last_close=float(close.iloc[-1]),
        volume_vs_20d_avg=(
            float(last_volume / volume_avg_20) if volume_avg_20 else None
        ),
    )


def _last_valid(series: pd.Series | None) -> float | None:
    """Return the last non-NaN value, or None if the series has no valid values yet
    (e.g. sma_200 on a ticker with under 200 bars — pandas_ta_classic returns None
    outright in that case, rather than a NaN-filled Series)."""
    if series is None:
        return None
    s = series.dropna()
    return float(s.iloc[-1]) if not s.empty else None
