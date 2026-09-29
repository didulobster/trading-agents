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


_MA_LABELS = {"sma_50": "50-day average", "sma_200": "200-day average"}


def _band_distance(close: float, lower: float, upper: float) -> str:
    """How FAR price sits from the Bollinger bands, as a clause to append.

    The side alone was not enough. On the FIG run (2026-08-29) the bear's
    whole technical leg was how overextended the close was — "3.5% above the
    upper Bollinger band" — a figure the relations did not state, so the model
    computed it from two pack values and the numeric guard reported it as
    possibly fabricated. It was neither fabricated nor wrong; it was
    (close − upper) / close, while the natural reading of "3.5% above the
    band" is (close − upper) / upper = 3.66%. Two defensible denominators and
    nothing telling the model which, on a number a reader takes at face value.

    So Python decides it, like every other comparison here, and the text names
    the denominator rather than leaving it inferable. Distances are measured
    against the BAND, the reference the phrase "above the band" is about.

    Only the bands the claim can be about: when price has broken out, the far
    band's distance is not a fact anyone argues from, and every number added
    here is one more value the containment guard has to hold. Within the
    bands, both distances are stated — "near the upper band" is a claim
    debaters make constantly, and it needs the same grounding as a breakout.
    """
    def pct(band: float) -> float:
        return (close - band) / band * 100

    if upper > 0 and close > upper:
        return f" — price is {pct(upper):.2f}% ABOVE the upper band (as a percentage of that band)"
    if lower > 0 and close < lower:
        return f" — price is {abs(pct(lower)):.2f}% BELOW the lower band (as a percentage of that band)"
    # Within the bands. A band of zero or less has no percentage to be a
    # denominator of — bb_lower can go negative on a volatile enough series —
    # so each side is stated only if it is meaningful, rather than dropping
    # both because one was not.
    parts = []
    if upper > 0:
        parts.append(f"{abs(pct(upper)):.2f}% BELOW the upper band")
    if lower > 0:
        parts.append(f"{pct(lower):.2f}% ABOVE the lower band")
    if not parts:
        return ""
    suffix = "each as a percentage" if len(parts) > 1 else "as a percentage"
    return f" — price is {' and '.join(parts)} ({suffix} of that band)"


def derive_relations(ind: TechnicalIndicators) -> list[str]:
    """State the comparisons in code rather than leaving them to the model.

    A live MSFT run produced "trading above its 50-day moving average (around
    419) but below its 200-day average (around 429)" while the last close was
    483.24 — above both. The model had collapsed two different facts, where
    price sits relative to each average and where the averages sit relative to
    each other, into one wrong claim. Every number in that sentence was
    genuine, so the flagged-numbers guard had nothing to catch.

    This is the same move as joining news items by index instead of letting
    the model retype them: whatever Python can decide, Python decides.
    """
    close = ind.last_close
    rel: list[str] = []

    for field, label in _MA_LABELS.items():
        value = getattr(ind, field)
        if value is not None:
            side = "ABOVE" if close > value else "BELOW"
            rel.append(f"last close ({close:.2f}) is {side} the {label} ({value:.2f})")

    if ind.sma_50 is not None and ind.sma_200 is not None:
        side = "ABOVE" if ind.sma_50 > ind.sma_200 else "BELOW"
        rel.append(
            f"the 50-day average ({ind.sma_50:.2f}) is {side} the 200-day average "
            f"({ind.sma_200:.2f}) — this is a statement about the two averages, "
            f"NOT about where price sits"
        )

    if ind.macd is not None and ind.macd_signal is not None:
        side = "ABOVE" if ind.macd > ind.macd_signal else "BELOW"
        rel.append(f"the MACD line ({ind.macd:.4f}) is {side} its signal line "
                   f"({ind.macd_signal:.4f})")

    if ind.rsi_14 is not None:
        band = (
            "OVERBOUGHT (>70)" if ind.rsi_14 > 70
            else "OVERSOLD (<30)" if ind.rsi_14 < 30
            else "NEITHER overbought nor oversold (between 30 and 70)"
        )
        rel.append(f"RSI ({ind.rsi_14:.2f}) is {band}")

    if ind.bb_upper is not None and ind.bb_lower is not None:
        where = (
            "ABOVE the upper band" if close > ind.bb_upper
            else "BELOW the lower band" if close < ind.bb_lower
            else "WITHIN the bands"
        )
        rel.append(f"last close ({close:.2f}) is {where} "
                   f"({ind.bb_lower:.2f} to {ind.bb_upper:.2f})"
                   + _band_distance(close, ind.bb_lower, ind.bb_upper))

    if ind.volume_vs_20d_avg is not None:
        side = "ABOVE" if ind.volume_vs_20d_avg > 1 else "BELOW"
        rel.append(f"latest volume is {side} its 20-day average "
                   f"({ind.volume_vs_20d_avg:.4f}x)")

    return rel
