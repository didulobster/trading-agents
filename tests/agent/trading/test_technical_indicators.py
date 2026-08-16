from pathlib import Path

import pandas as pd

from app.agent.trading.application.technical_indicators import compute_indicators

FIXTURE = Path(__file__).resolve().parents[3] / "tests/fixtures/avgo_ohlcv_sample.csv"


def test_compute_indicators_known_values():
    """Deterministic regression test, not an externally hand-verified check —
    expected values below were recorded by running compute_indicators() once
    against the frozen fixture on 2026-08-16, using pandas_ta_classic==0.6.52.
    This catches regressions in the indicator math or a library upgrade
    silently changing column names/output (see technical_indicators.py's
    module docstring flag on pandas-ta-classic column naming), not
    correctness against an independent source.
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
