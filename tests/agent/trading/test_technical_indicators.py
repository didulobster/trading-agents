from pathlib import Path

import pandas as pd

from app.agent.trading.application.technical_indicators import compute_indicators

FIXTURE = Path(__file__).resolve().parents[3] / "tests/fixtures/avgo_ohlcv_sample.csv"


def test_compute_indicators_known_values():
    """Deterministic regression test: the expected values below were recorded
    by running compute_indicators() once against the frozen fixture on
    2026-08-16, using pandas_ta_classic==0.6.52. This catches regressions in
    the indicator math or a library upgrade silently changing column
    names/output (see technical_indicators.py's module docstring flag on
    pandas-ta-classic column naming).

    It pins that the numbers are *stable*, not that they are *right* — a
    library computing RSI by the wrong convention would be frozen in here
    just as faithfully. The independent-implementation tests below cover
    that second question.
    """
    df = pd.read_csv(FIXTURE, index_col=0, parse_dates=True)
    result = compute_indicators(df)

    assert abs(result.sma_50 - 390.3289) < 0.01
    assert abs(result.sma_200 - 368.2457) < 0.01
    assert abs(result.rsi_14 - 46.5099) < 0.01
    assert abs(result.macd - 6.7920) < 0.01
    assert abs(result.macd_signal - 6.2253) < 0.01
    assert abs(result.macd_histogram - 0.5667) < 0.01
    assert abs(result.bb_upper - 434.5317) < 0.01
    assert abs(result.bb_mid - 399.4885) < 0.01
    assert abs(result.bb_lower - 364.4453) < 0.01
    assert abs(result.last_close - 392.9900) < 0.01
    assert abs(result.volume_vs_20d_avg - 1.6262) < 0.01


def test_compute_indicators_handles_insufficient_history_for_sma_200():
    """sma_200 should be None, not raise, when fewer than 200 valid bars exist —
    the _last_valid guard's actual reason for existing."""
    df = pd.read_csv(FIXTURE, index_col=0, parse_dates=True).tail(60)
    result = compute_indicators(df)

    assert result.sma_200 is None
    assert result.sma_50 is not None


# ---------------------------------------------------------------------------
# Independent verification of the indicator math.
#
# The regression test above pins pandas-ta-classic's output against itself, so
# it cannot tell a correct calculation from a consistently wrong one. These
# recompute the same indicators from their textbook definitions using nothing
# but pandas, and compare.
#
# Cross-checked once against the `ta` package (a separate codebase, not another
# call into pandas-ta-classic) on 2026-08-19: RSI, MACD line/signal/histogram,
# both SMAs and all three Bollinger bands agreed to six decimal places. `ta` is
# deliberately not a project dependency — these hand-rolled versions give the
# same independence permanently, without one.
# ---------------------------------------------------------------------------


def _wilder_rsi(close: pd.Series, length: int = 14) -> float:
    """RSI from Wilder's original definition: seed the average gain/loss with a
    simple mean of the first `length` periods, then smooth recursively by
    ((prev * (length - 1)) + current) / length.

    Written as an explicit loop rather than a pandas one-liner because the
    point is to share no code path, and no convention assumption, with the
    library under test.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.iloc[1 : length + 1].mean()
    avg_loss = loss.iloc[1 : length + 1].mean()
    for i in range(length + 1, len(close)):
        avg_gain = (avg_gain * (length - 1) + gain.iloc[i]) / length
        avg_loss = (avg_loss * (length - 1) + loss.iloc[i]) / length

    return 100 - 100 / (1 + avg_gain / avg_loss)


def _sma_rsi(close: pd.Series, length: int = 14) -> float:
    """The other RSI convention — a plain mean of the last `length` gains and
    losses, with no Wilder smoothing. Present only to show what a convention
    mismatch would look like, not as a correctness reference."""
    delta = close.diff()
    gain = delta.clip(lower=0).tail(length).mean()
    loss = (-delta.clip(upper=0)).tail(length).mean()
    return 100 - 100 / (1 + gain / loss)


def test_rsi_matches_an_independent_wilder_implementation():
    """pandas-ta-classic's RSI is Wilder-smoothed, confirmed against a
    from-scratch implementation rather than assumed from its documentation."""
    df = pd.read_csv(FIXTURE, index_col=0, parse_dates=True)
    result = compute_indicators(df)

    assert abs(result.rsi_14 - _wilder_rsi(df["Close"])) < 1e-4


def test_macd_matches_an_independent_ema_implementation():
    """MACD line, signal and histogram against plain pandas EWMs with
    adjust=False, the standard recursive EMA. By 251 bars any difference in
    how the initial EMA is seeded has long since decayed, so this should be
    an exact match rather than a close one."""
    df = pd.read_csv(FIXTURE, index_col=0, parse_dates=True)
    close = df["Close"]
    result = compute_indicators(df)

    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()

    assert abs(result.macd - macd.iloc[-1]) < 1e-4
    assert abs(result.macd_signal - signal.iloc[-1]) < 1e-4
    assert abs(result.macd_histogram - (macd.iloc[-1] - signal.iloc[-1])) < 1e-4


def test_the_wrong_rsi_convention_would_be_caught():
    """Establishes that the check above can actually discriminate.

    A test asserting agreement proves nothing unless disagreement is
    reachable: on this fixture the SMA-smoothed convention gives ~54.5
    against Wilder's ~46.5, a gap of roughly 8 points. So if a library
    upgrade quietly switched conventions, the Wilder comparison would fail by
    a wide margin rather than drift inside its tolerance.
    """
    df = pd.read_csv(FIXTURE, index_col=0, parse_dates=True)
    close = df["Close"]

    assert abs(_wilder_rsi(close) - _sma_rsi(close)) > 5.0
