import asyncio
from types import SimpleNamespace

import app.agent.trading.infrastructure.technical_interpreter_port as port
from app.agent.trading.domain.technical_report import TechnicalIndicators
from app.agent.trading.infrastructure.technical_interpreter_port import (
    _flag_unmatched_numbers,
    derive_relations,
    flag_contradicted_claims,
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
# Negative indicator values. Every fixture above is positive, but a bearish
# MACD is ordinary — these use the real values from a live V run whose
# macd_histogram was -1.2157936592253513, reported as "around -1.22".
# ---------------------------------------------------------------------------

BEARISH_INDICATORS = TechnicalIndicators(
    sma_50=330.1245,
    sma_200=317.8891,
    rsi_14=41.2033,
    macd=-2.4471,
    macd_signal=-1.2313,
    macd_histogram=-1.2157936592253513,
    bb_upper=352.11,
    bb_mid=335.42,
    bb_lower=318.73,
    last_close=327.55,
    volume_vs_20d_avg=0.8842,
)


def test_negative_values_reported_faithfully_do_not_false_positive():
    """Rounded restatements of negative indicators must match: the sign has
    to survive parsing in ordinary sentence positions (mid-sentence, after
    a preposition, inside parentheses, after an em-dash)."""
    text = (
        "The MACD line at -2.45 sits below its signal line at -1.23, with a "
        "bearish histogram of around -1.22. Momentum is weak — -1.22 confirms "
        "the crossover, and the histogram (-1.22) has not yet turned."
    )
    assert _flag_unmatched_numbers(text, BEARISH_INDICATORS) == []


def test_fabricated_negative_value_is_still_flagged():
    """The sign parsing must not become a hole: an invented negative value
    is caught like any other fabrication."""
    text = "The histogram is around -1.22, and a momentum score of -5.3 confirms weakness."
    assert _flag_unmatched_numbers(text, BEARISH_INDICATORS) == ["-5.3"]


def test_hyphenated_range_is_not_read_as_a_negative_number():
    """Real false positive, and a parsing bug rather than a tolerance one:
    'the 318.73-352.11 band' had its hyphen read as a minus sign, turning a
    faithful bb_upper mention into a fabricated '-352.11'. Unlike the
    accepted threshold false positives ('RSI above 70'), the number here was
    a genuine indicator value the scanner mangled before comparing it."""
    text = "Price trades within a Bollinger band spanning 318.73-352.11 currently."
    assert _flag_unmatched_numbers(text, BEARISH_INDICATORS) == []


def test_hyphenated_percentage_range_is_not_read_as_negative():
    """Same bug in the percent scanner: '88%-89%' must not parse its second
    endpoint as -89%. Both endpoints are faithful restatements of
    volume_vs_20d_avg=0.8842 (0.88 and 0.89 sit inside the ratio
    tolerance), so a correctly-parsed scan flags neither; before the fix
    the second one surfaced as a fabricated '-89%'."""
    text = "Volume ran 88%-89% of the 20-day average through the week."
    assert _flag_unmatched_numbers(text, BEARISH_INDICATORS) == []


def test_hyphenated_above_below_range_is_not_read_as_negative():
    """The third occurrence site of the range bug, and the one that needed
    more than the lookbehind. With volume_vs_20d_avg=1.2153 (+21.53% vs the
    20-day average), 'roughly 21%-22% above' is faithful at both endpoints.
    The sign parsed correctly once _SIGNED_NUMBER was applied here, but the
    pattern still matched only the endpoint touching the keyword, so
    consuming '22% above' orphaned '21%' for the general percent rule —
    which tested it as a ratio (0.21 vs 1.2153) when it is a delta, and
    flagged it. The match now spans both endpoints."""
    indicators = TechnicalIndicators(last_close=350.0, volume_vs_20d_avg=1.2153)
    text = "Volume ran roughly 21%-22% above the 20-day average."
    assert _flag_unmatched_numbers(text, indicators) == []


def test_fabricated_endpoint_in_above_below_range_is_still_flagged():
    """Spanning the range must not let a fabricated endpoint ride along:
    each endpoint is checked against the delta transform on its own."""
    indicators = TechnicalIndicators(last_close=350.0, volume_vs_20d_avg=1.2153)
    text = "Volume ran roughly 21%-99% above the 20-day average."
    assert _flag_unmatched_numbers(text, indicators) == ["99% above/below"]


def test_wide_above_below_range_flags_even_though_it_brackets_the_delta():
    """Documents a deliberate boundary, in the same spirit as
    test_flag_unmatched_numbers_does_not_catch_fabricated_period_label:
    endpoints are checked individually against the delta transform, not by
    asking whether the range brackets the true value. With
    volume_vs_20d_avg=1.225 the true delta is 22.5 and the tolerance is
    max(1.0, 1.225*2) = 2.45, so "20%-25% above" — which does contain 22.5
    — still flags, because each endpoint sits 2.5pp out.

    Containment was considered and rejected: it is the more natural
    reading of a range, but it would let an arbitrarily wide fabricated
    range ("0%-100% above average") bracket the true value and pass
    unflagged, which is the failure mode this guard exists to catch. If a
    real run ever produces a legitimately wide range, revisit this test
    rather than letting it silently start failing."""
    indicators = TechnicalIndicators(last_close=350.0, volume_vs_20d_avg=1.225)
    text = "Volume ran 20%-25% above the 20-day average this week."
    assert _flag_unmatched_numbers(text, indicators) == [
        "20% above/below",
        "25% above/below",
    ]


def test_fabricated_value_inside_a_range_is_still_flagged():
    """Range handling must not create a blind spot: a fabricated endpoint
    after the hyphen is still checked as a value, just a positive one."""
    text = "Price trades within a band spanning 318.73-999.99 currently."
    assert _flag_unmatched_numbers(text, BEARISH_INDICATORS) == ["999.99"]


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

    interpretation, flagged, _claims, _ = asyncio.run(
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

    _, flagged, _claims, _ = asyncio.run(
        interpret_indicators("AVGO", FULL_PRECISION_INDICATORS)
    )

    assert flagged == ["812"]


def test_bearish_interpretation_produces_no_flags(monkeypatch):
    """The negative-value path through the full wiring: a faithful bearish
    interpretation, where the sign is load-bearing on three separate
    values, must come back clean."""
    _mock_model_response(monkeypatch, (
        "V is in a bearish phase. The MACD line at -2.45 sits below its "
        "signal line at -1.23, leaving the histogram at around -1.22. RSI "
        "near 41 is soft without being oversold, and price at 327.55 sits "
        "in the lower half of the 318.73-352.11 Bollinger band."
    ))

    _, flagged, _claims, _ = asyncio.run(interpret_indicators("V", BEARISH_INDICATORS))

    assert flagged == []


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

    _, flagged, _claims, _ = asyncio.run(
        interpret_indicators("AVGO", FULL_PRECISION_INDICATORS)
    )

    assert flagged == []


# ---------------------------------------------------------------------------
# Contradicted claims — regression from a live MSFT run (2026-08-23)
# ---------------------------------------------------------------------------

def _msft_indicators() -> TechnicalIndicators:
    """The real values behind the failure: price above BOTH averages, while
    the 50-day sits below the 200-day."""
    return TechnicalIndicators(
        sma_50=419.09196105957034,
        sma_200=429.4326626586914,
        rsi_14=62.95966955766375,
        bb_upper=545.57376730238,
        bb_mid=472.2936721801758,
        bb_lower=399.0135770579716,
        last_close=483.239990234375,
        volume_vs_20d_avg=0.6135848256630001,
    )


def test_flags_the_exact_sentence_the_model_produced():
    """Verbatim from the MSFT run. Every number in it is genuine, which is why
    the numbers guard passed it and it reached the decision memo."""
    text = (
        "MSFT is trading above its 50-day moving average (around 419) but below "
        "its 200-day average (around 429), indicating a mixed intermediate trend."
    )

    flags = flag_contradicted_claims(text, _msft_indicators())

    assert len(flags) == 1
    assert "below the 200-day average" in flags[0]
    assert "483.24" in flags[0]
    # the 'above the 50-day' half of the same sentence is true and must not flag
    assert "50-day" not in flags[0]


def test_does_not_flag_a_true_comparison_between_two_averages():
    """The tightest false-positive risk: identical words, different subject.
    'the 50-day is below the 200-day' is true here and must pass."""
    text = (
        "The 50-day moving average is below the 200-day moving average, "
        "a bearish structure."
    )

    assert flag_contradicted_claims(text, _msft_indicators()) == []


def test_does_not_flag_correct_price_claims():
    text = (
        "MSFT is trading above its 50-day moving average and above its 200-day "
        "average, confirming strength."
    )

    assert flag_contradicted_claims(text, _msft_indicators()) == []


def test_flags_a_below_claim_when_price_is_genuinely_above_only():
    ind = _msft_indicators()
    ind.last_close = 400.0     # now genuinely below both averages

    correct = "Price is below its 50-day average and below its 200-day average."
    wrong = "Price is above its 50-day average."

    assert flag_contradicted_claims(correct, ind) == []
    assert len(flag_contradicted_claims(wrong, ind)) == 1


def test_unavailable_indicator_is_not_a_contradiction():
    """A None sma_200 means nothing to compare against; silence beats a
    fabricated verdict either way."""
    ind = _msft_indicators()
    ind.sma_200 = None

    text = "MSFT is trading below its 200-day average."

    assert flag_contradicted_claims(text, ind) == []


def test_claim_check_does_not_run_across_sentences():
    """'below' in one sentence and a 200-day mention in the next are unrelated;
    matching across the boundary would invent a claim nobody made."""
    text = (
        "Volume is below its recent norm. The 200-day average sits at 429."
    )

    assert flag_contradicted_claims(text, _msft_indicators()) == []


# ---------------------------------------------------------------------------
# Derived relations handed to the model
# ---------------------------------------------------------------------------

def test_relations_state_price_and_average_comparisons_separately():
    rel = "\n".join(derive_relations(_msft_indicators()))

    assert "last close (483.24) is ABOVE the 50-day average" in rel
    assert "last close (483.24) is ABOVE the 200-day average" in rel
    # the fact the model confused it with, explicitly labelled as different
    assert "the 50-day average (419.09) is BELOW the 200-day average" in rel
    assert "NOT about where price sits" in rel


def test_relations_skip_indicators_that_were_not_computed():
    ind = _msft_indicators()
    ind.sma_200 = None
    ind.macd = None

    rel = "\n".join(derive_relations(ind))

    assert "200-day" not in rel
    assert "MACD" not in rel
    assert "50-day average" in rel


def test_relations_report_rsi_band_and_volume_side():
    ind = _msft_indicators()
    rel = "\n".join(derive_relations(ind))
    assert "NEITHER overbought nor oversold" in rel
    assert "volume is BELOW its 20-day average" in rel

    ind.rsi_14 = 82.0
    assert "OVERBOUGHT" in "\n".join(derive_relations(ind))


def test_does_not_flag_the_corrected_model_output(monkeypatch):
    """Verbatim from the live re-run after the relations block was added. The
    model gets it right here, and an earlier version of this guard flagged it
    anyway: the exclusion only recognised finite verbs, so the participle in
    "the 50-day average sitting below the 200-day average" slipped past and
    correct prose was reported as a contradiction."""
    text = (
        "MSFT is trading above both its 50-day and 200-day moving averages, "
        "showing an uptrend, though the 50-day average sitting below the "
        "200-day average indicates the intermediate-term momentum is weaker "
        "than the longer-term trend. The RSI at 62.96 shows moderate bullish "
        "momentum without reaching overbought territory."
    )

    assert flag_contradicted_claims(text, _msft_indicators()) == []


def test_exclusion_covers_varied_verb_forms_but_not_the_real_error():
    """The boundary the exclusion has to hold: bare words between the average
    and the comparator mean the average is the subject; anything else (a
    parenthetical, a conjunction) means it is not."""
    ind = _msft_indicators()

    for phrasing in (
        "The 50-day average is below the 200-day average.",
        "The 50-day average sitting below the 200-day average is bearish.",
        "The 50-day moving average has slipped below the 200-day average.",
        "The 50-day averages remain below the 200-day average.",
    ):
        assert flag_contradicted_claims(phrasing, ind) == [], phrasing

    # the real failure: an average appears shortly before the comparator, but
    # price is still the subject
    real = (
        "MSFT is trading above its 50-day moving average (around 419) but "
        "below its 200-day average (around 429)."
    )
    assert len(flag_contradicted_claims(real, ind)) == 1


def test_does_not_flag_the_elided_average_phrasing():
    """Second live false positive: the model dropped the noun altogether —
    "the 50-day sitting below the 200-day" — so a pattern anchored on the word
    "average" had nothing to match and flagged correct prose. Verbatim from
    the run after the participle fix."""
    text = (
        "MSFT is in an uptrend with price at 483.24 trading above both its "
        "50-day average (419.09) and 200-day average (429.43), though the "
        "50-day sitting below the 200-day suggests some intermediate weakness "
        "in the trend structure."
    )

    assert flag_contradicted_claims(text, _msft_indicators()) == []


def test_two_word_margin_does_not_swallow_a_following_price_claim():
    """The exclusion allows two bare words, and that limit is load-bearing: a
    genuine price claim further along the same sentence must still be checked
    rather than absorbed by the preceding average reference."""
    text = (
        "The 50-day average is below the 200-day average, but the price is "
        "below its 200-day average."
    )

    flags = flag_contradicted_claims(text, _msft_indicators())

    assert len(flags) == 1
    assert "483.24" in flags[0]
