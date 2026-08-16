from app.agent.trading.domain.technical_report import TechnicalIndicators
from app.agent.trading.infrastructure.technical_interpreter_port import (
    _flag_unmatched_numbers,
)

INDICATORS = TechnicalIndicators(
    sma_50=390.33,
    sma_200=368.25,
    rsi_14=46.51,
    macd=6.79,
    macd_signal=6.23,
    macd_histogram=0.57,
    bb_upper=434.53,
    bb_mid=399.49,
    bb_lower=364.45,
    last_close=392.99,
    volume_vs_20d_avg=1.63,
)


def test_period_labels_do_not_false_positive():
    """Real regression: 'the 50-day moving average... 200-day average...
    1.6 times the 20-day average' previously flagged 50/200/20 even though
    they're SMA/volume window labels, not fabricated data."""
    text = (
        "AVGO is in a moderate uptrend with the 50-day moving average (around 390) "
        "above the 200-day average (around 368). RSI at around 46.5 is neutral. "
        "MACD histogram is around 0.57. Volume is 1.6 times the 20-day average."
    )
    assert _flag_unmatched_numbers(text, INDICATORS) == []


def test_genuinely_fabricated_value_is_still_flagged():
    """The guard's actual job: a value that doesn't correspond to anything in
    `indicators` should still be caught."""
    text = "RSI is around 46.5, and the stock has a P/E ratio of 812 currently."
    assert _flag_unmatched_numbers(text, INDICATORS) == ["812"]


def test_flag_unmatched_numbers_does_not_catch_fabricated_period_label():
    """Documents a known, accepted gap: stripping '<N>-day' phrases before the
    value-check means a fabricated period reads as a label, not data, and slips
    through unflagged. This test exists so the boundary is asserted and visible
    in CI, not just described in a comment — if someone tightens the regex later,
    this test should be revisited rather than silently start failing."""
    text = "The 55-day moving average confirms the trend."
    assert _flag_unmatched_numbers(text, INDICATORS) == []


def test_ratio_reported_as_percentage_does_not_false_positive():
    """Real regression: volume_vs_20d_avg=0.5291233813779816 was faithfully
    reported as 'about 53% of the 20-day average' (ratio * 100), which the
    plain-number check alone would flag as fabricated since 53 doesn't match
    any raw indicator value — only its percentage form does."""
    indicators = TechnicalIndicators(last_close=24.10, volume_vs_20d_avg=0.5291233813779816)
    text = "Volume is light, running at about 53% of the 20-day average."
    assert _flag_unmatched_numbers(text, indicators) == []


def test_fabricated_percentage_is_still_flagged():
    """Percent-normalization shouldn't swallow a genuinely fabricated
    percentage — only ones that map back to a real ratio value."""
    indicators = TechnicalIndicators(last_close=24.10, volume_vs_20d_avg=0.5291233813779816)
    text = "Volume is running at about 53% of average, with 90% analyst buy ratings."
    assert _flag_unmatched_numbers(text, indicators) == ["90%"]
