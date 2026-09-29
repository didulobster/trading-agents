"""Grounding checks: does a figure or stated direction have support in the
evidence pack? Pure functions — no LLM, no network."""

from __future__ import annotations

import pytest

from app.agent.trading.infrastructure.evidence import (
    contradicted_directions,
    unbacked_figures,
)


# ---------------------------------------------------------------------------
# (b) Numeric fabrication guard
# ---------------------------------------------------------------------------

PACK = (
    "FUNDAMENTALS:\nRevenue grew to 64.9 billion, operating margin 34.1%.\n"
    "TECHNICAL: last_close 327.55, volume_vs_20d_avg 0.529, rsi_14 41.2033."
)


def test_a_figure_absent_from_the_pack_is_flagged():
    assert unbacked_figures("Revenue reached 71.4 billion.", PACK) == ["71.4"]


def test_a_rounded_restatement_of_a_pack_value_is_not_flagged():
    """Prose rounds figures. Both of the first two live turns produced one of
    these — "RSI of 41.2" for 41.2033, "the 50-day at 330.12" for 330.1245 —
    a 100% false-positive rate on day one. A guard that cries wolf teaches
    the reader to skip it, and then it is not there for the one that
    matters."""
    assert unbacked_figures("RSI of 41.2 is neutral.", PACK) == []
    assert unbacked_figures("The 50-day sits at 327.6.", PACK) == []


def test_rounding_clearance_is_scoped_to_the_figure_s_own_precision():
    """Not a tolerance band. "41.2" clears only against a value in
    [41.15, 41.25), so the blind spot does not widen as the pack grows —
    which is the whole reason containment replaced tolerance here."""
    assert unbacked_figures("RSI of 41.3 is neutral.", PACK) == ["41.3"]
    assert unbacked_figures("RSI of 41.21 is neutral.", PACK) == ["41.21"]


def test_a_percent_written_against_a_percent_in_the_pack_is_not_flagged():
    """The pack states "operating margin 34.1%"; the debater writes "34%".
    Neither containment nor the ratio transform clears that — rounding
    does."""
    assert unbacked_figures("A margin of 34%.", PACK) == []


def test_a_figure_present_in_the_pack_is_not_flagged():
    assert unbacked_figures("Revenue of 64.9 billion.", PACK) == []


def test_a_faithful_percent_restatement_of_a_ratio_is_not_flagged():
    """volume_vs_20d_avg 0.529 reported as "53%" is faithful; containment
    alone would flag it, which is why percent forms get the Phase 3
    transforms."""
    assert unbacked_figures("Volume sits at 53% of its average.", PACK) == []


def test_a_fabricated_percent_is_still_flagged():
    assert unbacked_figures("Volume sits at 88% of its average.", PACK) == ["88%"]


@pytest.mark.parametrize(
    "text",
    [
        "downside is unconstrained until the low-30s oversold zone",
        "negative MACD and sub-50-SMA price action",
        "the post-2020 build-out",
    ],
)
def test_a_hyphenated_compound_is_not_read_as_a_negative_number(text):
    """Found on the first live debate (AVGO, 2026-08-23): "low-30s" and
    "sub-50-SMA" were reported as the fabricated figures -30 and -50 — two of
    that run's six flags, so it is not a rare shape.

    The lookbehind has to cover the digit as well as the sign. Blocking only
    "<letter>-<digits>" would let the scanner start one character later and
    flag a bare "30" out of "low-30s" — the same false positive with the sign
    filed off.
    """
    assert unbacked_figures(text, PACK) == []


def test_a_range_endpoint_is_still_read_as_a_positive_number():
    """The other half of the same lookbehind, from Phase 3: a hyphen between
    two digits is a range separator, and both endpoints are real values."""
    pack = "TECHNICAL: bb_lower 353.79, bb_upper 438.34."
    assert unbacked_figures("the band runs 353.79-438.34", pack) == []
    assert unbacked_figures("the band runs 353.79-999.99", pack) == ["999.99"]


def test_a_genuine_negative_number_still_parses():
    pack = "TECHNICAL: macd_histogram -5.8513."
    assert unbacked_figures("a histogram of -5.85", pack) == []
    assert unbacked_figures("a histogram of -9.99", pack) == ["-9.99"]


def test_period_labels_are_not_treated_as_data():
    assert unbacked_figures("Above its 200-day average.", PACK) == []


def test_typographic_minus_is_normalized_before_the_sign_is_read():
    """The model writes U+2212 roughly one run in four. float() agrees on the
    narrower alphabet, so an unnormalized minus parses as a positive number
    and matches nothing."""
    pack = "TECHNICAL: macd_histogram -1.2158."
    assert unbacked_figures("The histogram is −1.2158.", pack) == []


def test_the_same_fabricated_figure_repeated_is_one_finding():
    text = "71.4 billion, up from 71.4 the prior year, so 71.4 stands."
    assert unbacked_figures(text, PACK) == ["71.4"]


def test_a_decline_written_as_a_negative_clears_against_an_unsigned_source():
    """Found on the discrimination probe (MSFT, 2026-08-29). The news feed
    states a decline in words — "Cuts Share Stake In Microsoft Corp By 36.8%"
    — and the debater wrote it as a signed delta, "Viking -36.8%". That was
    reported to the reader as a possibly fabricated figure in the memo's data
    gaps, on a run whose only other flags were real. Prose puts the direction
    in the verb; a debater putting it in the sign is restating, not
    inventing."""
    pack = "NEWS: Viking Global Investors Cuts Share Stake In Microsoft Corp By 36.8%."
    assert unbacked_figures("Investors are exiting (Viking -36.8%).", pack) == []
    assert unbacked_figures("Investors are exiting (Viking 36.8%).", pack) == []


def test_a_source_negative_restated_without_its_sign_also_clears():
    """The same equivalence in the other direction: the pack carries the sign
    and the prose carries the word."""
    pack = "FUNDAMENTALS: free cash flow of -44,708 million."
    assert unbacked_figures("FCF was negative 44,708 million.", pack) == []


def test_a_sign_inversion_of_a_sourced_figure_is_no_longer_reported():
    """The cost of the two tests above, asserted rather than left to be
    discovered from a memo. This guard answers "does this figure have a
    source", and a magnitude in the pack was not invented; reading it in the
    wrong direction is a different defect needing a check that knows what the
    number means."""
    pack = "FUNDAMENTALS: revenue grew 5.2% year over year."
    assert unbacked_figures("Revenue fell -5.2%.", pack) == []


def test_magnitude_matching_does_not_widen_the_guard_beyond_the_sign():
    """A figure absent from the pack is still flagged at either sign — the
    change is an equivalence between "-x" and "x", not a tolerance."""
    assert unbacked_figures("Revenue reached -71.4 billion.", PACK) == ["-71.4"]


# ---------------------------------------------------------------------------
# (d2) Direction guard — the figures are right and the sentence is not
#
# Every false-positive case below is a real sentence from the vault that an
# earlier version of this guard flagged. The corpus is the test: over 36
# transcripts the shipped version returns exactly one finding, the NFLX one.
# ---------------------------------------------------------------------------

def test_a_trend_word_contradicted_by_its_own_figures_is_flagged():
    """The finding this exists for, live on two NFLX runs a day apart. Both
    figures are in the fundamentals memo, so the number guard cleared them and
    the quote check had nothing to say — and 832 against 1,351 is the gap
    NARROWING."""
    found = contradicted_directions(
        "a persistent OCF/NI gap that is widening — FY2025 gap of $832M "
        "versus FY2024's $1,351M shortfall."
    )

    assert found == ["'widening' but FY2025 832M is below FY2024 1,351M"]


def test_a_trend_word_its_figures_agree_with_is_silent():
    assert contradicted_directions(
        "Revenue grew from $477,839K in H1 2025 to $703,522K in H1 2026."
    ) == []
    assert contradicted_directions(
        "The gap narrowed from $1.351B in FY2024 to $832M in FY2025."
    ) == []


def test_figures_written_before_their_period_still_pair_correctly():
    """AVGO, 2026-08-29 — a CORRECT claim the first version flagged. Reading
    only "period then figure" paired FY2024 with the number on the far side of
    it, and inverted the comparison."""
    assert contradicted_directions(
        "Total debt/operating income fell from 5.19x (FY2024) to 2.63x "
        "(FY2025), below the 3.0x trip-line."
    ) == []


def test_a_deepening_decline_is_not_a_contradiction():
    """ACN, 2026-08-29 — "bookings declined ~1% FY2025 and 2-3% Q3 FY2026" is
    a decline getting worse, and its figures rise. A delta carries its
    direction in the verb."""
    assert contradicted_directions(
        "Leading indicator declined ~1% FY2025 and 2-3% Q3 FY2026."
    ) == []
    assert contradicted_directions(
        "The order-book risk is the declining leading indicator "
        "(bookings \u22121% FY2025, \u22122-3% Q3 FY2026)."
    ) == []


def test_a_verb_governing_a_different_quantity_is_not_read_against_the_years():
    """FIG, 2026-08-29 — the years carry FCF and "grew" belongs to revenue,
    which has no year attached. The trend word must PRECEDE the figures it is
    read against."""
    assert contradicted_directions(
        "FCF fell 8.6% YoY (H1 2026 $141.8M vs H1 2025 $155.2M) while revenue "
        "grew +47.2%."
    ) == []


def test_a_form_name_is_not_a_figure():
    """NFLX risk panel — "the FY2026 10-K shows" offered 10 as FY2026's
    figure, against a real $832M for FY2025."""
    assert contradicted_directions(
        "If the FY2026 10-K shows OCF trailing NI by less than the FY2025 gap "
        "of ~$832M, with content cash additions growing no faster than "
        "amortization, I lower severity."
    ) == []


def test_a_markdown_row_is_not_one_sentence():
    """FIG, 2026-08-24 — a metrics table joined a revenue figure to a verb
    from the claim row beneath it."""
    assert contradicted_directions(
        "| Revenue FY2025 $1,055.8M For H1 2026 SBC expense: $316.6M | "
        "`ar-divergence` | Accounts receivable grew 88.8% |"
    ) == []


def test_two_quantities_of_different_units_are_never_compared():
    assert contradicted_directions(
        "IC margin fell to 41.3% in FY2026 from revenue of $106,265M in FY2025."
    ) == []


def test_an_ambiguous_direction_word_says_nothing():
    """A deteriorating ratio falls and a deteriorating gap rises. Neither
    vocabulary claims it."""
    assert contradicted_directions(
        "Earnings quality is deteriorating — FY2025 at $832M against FY2024's "
        "$1,351M."
    ) == []


def test_four_periods_in_one_sentence_are_left_alone():
    """Which pair the trend word governs is a question this cannot answer, so
    it does not try. (A semicolon would split this into two sentences, which
    is why the real MSFT line — which carries no trend word at all — never
    reaches the comparison either.)"""
    assert contradicted_directions(
        "Margins are falling, with PBP FY2026 at 59.9% vs FY2025 57.8% and IC "
        "FY2026 at 41.3% vs FY2025 42.0%."
    ) == []


# ---------------------------------------------------------------------------
# Scale-aware clearing (2026-08-27). Measured on three live Phase 9 memos:
# every "may be fabricated" figure the guard reported was correct, and every
# one was a millions-to-billions restatement it could not see. Seven false
# positives, zero true positives -- a guard whose warnings are reliably
# wrong teaches the reader to skip the category.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw, pack_value", [
    ("63.9", 63887.0),    # AVGO revenue, $63,887M -> "$63.9B"
    ("35.8", 35819.0),    # AVGO FY2023 revenue
    ("5.7", 5747.0),      # AVGO FY2024 SBC
    ("10.1", 10149.0),    # NFLX operating cash flow
    ("69.7", 69673.0),    # ACN revenue
])
def test_a_millions_to_billions_restatement_clears(raw, pack_value):
    assert unbacked_figures(raw, str(pack_value)) == []


def test_same_scale_rounding_still_clears():
    assert unbacked_figures("41.2", "41.2033") == []


@pytest.mark.parametrize("raw", ["70", "100", "64"])
def test_a_bare_integer_never_clears_by_scale(raw):
    """The safety argument for scale clearing. Dividing the pack by 1000
    widens what the guard will clear against, and for an integer that window
    is 1000 values wide -- "70" would clear against anything in
    [69500, 70500). A real unit conversion keeps its significant digits
    ("$63.9B", never "$64B"), because keeping them is the point of
    converting, so requiring a decimal admits the restatements and admits
    none of the round inventions."""
    assert unbacked_figures(raw, "69673.0 63887.0 100400.0") == [raw]


def test_a_near_miss_at_the_same_precision_still_fails():
    assert unbacked_figures("63.8", "63887.0") == ["63.8"]
