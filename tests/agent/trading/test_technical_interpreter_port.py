import asyncio
from types import SimpleNamespace

import app.agent.trading.infrastructure.technical_interpreter_port as port
from app.agent.trading.domain.technical_report import TechnicalIndicators
from app.agent.trading.infrastructure.technical_interpreter_port import (
    _flag_unmatched_numbers,
    interpret_indicators,
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


def test_percentage_above_average_does_not_false_positive():
    """Real regression, distinct from the 'N% of' case: volume_vs_20d_avg
    =1.2153 was faithfully reported as 'about 22% above the 20-day average'
    — a delta from the ratio ((1.2153-1)*100=21.5% =~ 22), not the raw
    ratio-as-percentage (that would be 122%, a different phrasing)."""
    indicators = TechnicalIndicators(last_close=350.0, volume_vs_20d_avg=1.2153)
    text = "Volume is elevated, running about 22% above the 20-day average."
    assert _flag_unmatched_numbers(text, indicators) == []


def test_fabricated_above_below_percentage_is_still_flagged():
    """The above/below transform shouldn't swallow a genuinely fabricated
    delta percentage — only ones that map back to a real ratio value."""
    indicators = TechnicalIndicators(last_close=350.0, volume_vs_20d_avg=1.2153)
    text = "Volume is running about 22% above average, with sentiment 90% above normal."
    assert _flag_unmatched_numbers(text, indicators) == ["90% above/below"]


# ---------------------------------------------------------------------------
# Step-4 isolation: interpret_indicators end-to-end against a mocked model
# response — no live vendor call, no API key, no cost-log side effect. The
# direct _flag_unmatched_numbers tests above check the guard's matching
# rules; these check the wiring: response text assembly -> guard -> the
# (interpretation, flagged) tuple callers actually receive.
# ---------------------------------------------------------------------------

# Full-precision values, shaped as compute_indicators actually emits them —
# the interpretation's rounded restatements ("around 62", "1.6 times") must
# survive the guard against unrounded floats, not test-friendly 2dp ones.
FULL_PRECISION_INDICATORS = TechnicalIndicators(
    sma_50=390.3348,
    sma_200=368.2541,
    rsi_14=62.3719,
    macd=6.7893,
    macd_signal=6.2277,
    macd_histogram=0.5616,
    bb_upper=434.5289,
    bb_mid=399.4901,
    bb_lower=364.4513,
    last_close=392.99,
    volume_vs_20d_avg=1.6312,
)


def _mock_model_response(monkeypatch, text: str) -> None:
    """Stand in for AsyncAnthropic with a canned response, and neutralize
    log_cost so tests don't append to the real docs/cost-log.jsonl."""

    class FakeClient:
        def __init__(self):
            self.messages = SimpleNamespace(create=self._create)

        async def _create(self, **kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=text)],
                usage=SimpleNamespace(
                    input_tokens=100,
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=0,
                    output_tokens=80,
                ),
            )

    monkeypatch.setattr(port, "AsyncAnthropic", FakeClient)
    monkeypatch.setattr(port, "log_cost", lambda *args, **kwargs: None)


def test_normal_interpretation_produces_no_flags(monkeypatch):
    """A faithful interpretation — every number a rounded restatement of a
    supplied indicator value — must come back with an empty flagged list."""
    _mock_model_response(monkeypatch, (
        "AVGO is in an uptrend, with the 50-day moving average around 390 "
        "holding above the 200-day average around 368. RSI at around 62 "
        "shows healthy momentum without being overbought. The MACD line at "
        "6.79 sits above its signal line at 6.23, with a positive histogram "
        "of 0.56. Volume is running about 1.6 times the 20-day average, "
        "supporting the move."
    ))

    interpretation, flagged = asyncio.run(
        interpret_indicators("AVGO", FULL_PRECISION_INDICATORS)
    )

    assert flagged == []
    assert "uptrend" in interpretation  # the mocked text is what comes back


def test_injected_fabricated_number_is_flagged_through_interpret(monkeypatch):
    """Manually inject an obviously fabricated value into the mocked
    response: the guard must catch it in the flagged list callers receive
    from interpret_indicators, not just when invoked directly."""
    _mock_model_response(monkeypatch, (
        "RSI at around 62 shows healthy momentum. The stock's P/E ratio "
        "of 812 suggests rich valuation."
    ))

    _, flagged = asyncio.run(
        interpret_indicators("AVGO", FULL_PRECISION_INDICATORS)
    )

    assert flagged == ["812"]


def test_injected_fabricated_period_slips_through_mocked_response(monkeypatch):
    """The documented period-label boundary, asserted through the full
    interpret path: a fabricated '55-day average' is stripped as a window
    label before the value-check runs, so it comes back unflagged. This
    exists so the gap stays visible where callers actually consume the
    guard — if the period-strip regex is ever tightened, revisit this test
    rather than letting it silently start failing."""
    _mock_model_response(monkeypatch, (
        "The 55-day moving average confirms the trend, with RSI around 62."
    ))

    _, flagged = asyncio.run(
        interpret_indicators("AVGO", FULL_PRECISION_INDICATORS)
    )

    assert flagged == []
