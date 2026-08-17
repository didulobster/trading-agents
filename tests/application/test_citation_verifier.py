from app.application.citation_verifier import verify_answer
from app.application.memo_verifier import verify_memo


def test_number_matching_unretried_rejected_calc_is_flagged_not_unverified():
    """Reproduces the reported ACN gap: FCF growth of 26.2% is real text
    present in the corpus (so it passes as verified), but the calculate()
    call that was supposed to back it was rejected and never retried. That
    must land in `flagged`, distinct from `unverified` — the number isn't
    fabricated, its derivation just isn't backed by a passing tool call."""
    answer = "Free cash flow grew 26.2% year over year."
    corpus = {0: "Free cash flow grew 26.2% year over year, per the MD&A."}
    rejected = [{
        "value": 26.233,
        "reason": "Rejected: fiscal-period mismatch",
        "expression": "(10874.4 - 8614.518) / 8614.518 * 100",
    }]

    report = verify_answer(answer, corpus, computed_values=[], rejected_calcs=rejected)

    assert report.ok  # not fabricated — it's genuinely in the corpus
    assert len(report.flagged) == 1
    assert report.flagged[0].value == "26.2"


def test_number_matching_retried_calc_is_not_flagged():
    """If the same value also appears in computed_values (a later passing
    calculate() call), it must not be flagged — the derivation was in fact
    validated this run."""
    answer = "Free cash flow grew 26.2% year over year."
    corpus = {0: "Free cash flow grew 26.2% year over year, per the MD&A."}
    rejected = [{
        "value": 26.233,
        "reason": "Rejected: fiscal-period mismatch",
        "expression": "(10874.4 - 8614.518) / 8614.518 * 100",
    }]

    report = verify_answer(
        answer, corpus, computed_values=[26.233], rejected_calcs=rejected
    )

    assert report.flagged == []


def test_near_boundary_rounding_error_still_matches_rejected_calc():
    """Reproduces the reported ACN gap: an Asia Pacific segment margin whose
    rejected calculate() call ('1810.0 / 9972.305 * 100') truly evaluates to
    18.1503 (rounds to 18.2), but the memo states 18.1 — the model's own
    rounding error, off the true value by ~0.05. The prior matcher compared
    pre-rounded string forms of both sides ({"18.2","18.15"} vs {"18.1"}),
    which never intersect no matter how the true value is rounded, since
    18.1 isn't a rounded form of 18.1503 at all. Five sibling segment-margin
    figures that happened to round cleanly were caught; this near-boundary
    one wasn't — until matching became a numeric distance check."""
    answer = "Asia Pacific operating margin was 18.1% in FY2025."
    corpus = {0: answer}
    rejected = [{
        "value": 1810.0 / 9972.305 * 100,
        "reason": "Rejected: no tool returned these figures during this run: 9972.305",
        "expression": "1810.0 / 9972.305 * 100",
    }]

    report = verify_answer(answer, corpus, computed_values=[], rejected_calcs=rejected)

    assert len(report.flagged) == 1
    assert report.flagged[0].value == "18.1"


def test_unrelated_number_far_from_any_rejected_value_is_not_flagged():
    """The numeric-tolerance matcher must stay tight enough not to flag
    figures that simply aren't related to any rejected calculation."""
    answer = "Revenue was 64270 in FY2023."
    corpus = {0: answer}
    rejected = [{
        "value": 18.15,
        "reason": "Rejected: fiscal-period mismatch",
        "expression": "1810.0 / 9972.305 * 100",
    }]

    report = verify_answer(answer, corpus, computed_values=[], rejected_calcs=rejected)

    assert report.flagged == []


def test_fabricated_segment_figures_no_longer_hide_inside_bigger_numbers():
    """Reproduces the reported ACN fabrication: three invented segment-level
    restructuring figures ($420.5M, $83.2M, $44.6M) with no tool call
    behind them at all — no calculate() call, rejected or otherwise, and no
    quote wrapper. The bug: the old substring check (`variant in text`)
    treated a memo number as verified merely because its digits occurred
    *inside* an unrelated, larger corpus number — 420.5 is a substring of
    3,420.5; 83.2 of 1,283.2; 44.6 of 2,344.63. None of these three numbers
    were ever actually retrieved; all three must land in `unverified`."""
    answer = (
        "Section 5. Americas recorded $420.5M in restructuring charges in "
        "FY2025 compared to $83.2M in FY2024, against a company-wide total "
        "of $615M in FY2025 and $438M in FY2024. EMEA's improvement "
        "reflects lower business optimization costs in the region "
        "($44.6M in FY2025)."
    )
    corpus = {0: (
        "Total business optimization costs were $615 million in FY2025 "
        "and $438 million in FY2024. Segment operating margins were 15%, "
        "13%, and 18% respectively. A separate rollforward table shows "
        "$3,420.5 thousand, $1,283.2 million, and $2,344.63 million for "
        "unrelated line items."
    )}

    report = verify_answer(answer, corpus, computed_values=[], rejected_calcs=[])

    unverified_values = {f.value for f in report.unverified}
    assert {"420.5", "83.2", "44.6"} <= unverified_values
    # the real, actually-retrieved aggregate figures must still verify
    verified_values = {f.value for f in report.verified}
    assert {"615", "438"} <= verified_values


def test_truncated_decimal_still_matches_more_precise_corpus_figure():
    """The one legitimate case the old substring check existed for must
    still work: a memo rounds/truncates a filing's more precise figure
    (filing states 1,364.1, memo writes 1364) — this is a real match, at
    the number's own boundary, not a coincidental mid-token collision."""
    answer = "Total debt was 1364 at fiscal year end."
    corpus = {0: "Total debt outstanding was $1,364.1 million at year end."}

    report = verify_answer(answer, corpus, computed_values=[], rejected_calcs=[])

    assert report.unverified == []
    assert len(report.verified) == 1


def test_fabricated_table_figures_cannot_verify_against_percentages():
    """Reproduces the second reported ACN fabrication: a fully invented
    three-year OCF/capex table ($11,474.4M / $9,131.0M / $9,524.3M and
    $600.0M / $516.5M / $528.2M) whose six numbers appear nowhere in the
    tool trace — the only cash-flow ask_edgar calls explicitly said the
    data wasn't retrievable. They evaded the token-anchored check via the
    scale fallback's old symmetric tolerance: after dividing by 1000, its
    0.05 absolute floor was a ±50 window on the original number, so
    11,474.4/1000 ≈ 11.47 'matched' an unrelated '11.5%' in prose and
    516.5/1000 ≈ 0.5165 'matched' a citation similarity score sim=0.516.
    With direction-aware tolerances (and sim scores kept out of the corpus
    at the source, tested separately in test_tools), a fabricated figure
    can no longer verify against percentages it has no relation to."""
    corpus = {0: (
        "The filing does not contain the complete operating cash flow "
        "figures. Revenue grew 11.5% in local currency. Operating margin "
        "was 9.1% for one segment and 9.5% for another. Free cash flow "
        "was 10,874.36.\nSources:\n  [ACN 10-K 2025 §Item 7] sim=\n"
        "  [ACN 10-K 2025 §Item 8] sim="
    )}
    memo = (
        "| Operating Cash Flow ($M) | 11,474.4 | 9,131.0 | 9,524.3 |\n"
        "| Capital Expenditures ($M) | 600.0 | 516.5 | 528.2 |\n"
        "Free cash flow was 10,874.36 in FY2025."
    )

    report = verify_answer(memo, corpus, computed_values=[], rejected_calcs=[])

    unverified = {f.value for f in report.unverified}
    assert {"11,474.4", "9,131.0", "9,524.3", "600.0", "516.5", "528.2"} <= unverified
    assert {f.value for f in report.verified} == {"10,874.36"}


def test_scale_restatement_of_real_figure_still_verifies():
    """The legitimate cases the scale fallback exists for must survive the
    tightened tolerances: a thousands-scale corpus figure restated rounded
    in millions (877,433 -> 877.4), and the same restated to a whole
    number (615,433 -> 615) — the memo's precision is its rounding slop,
    half a step in the last displayed decimal."""
    corpus = {0: (
        "Total revenues were $877,433 thousand. Business optimization "
        "costs were $615,433 thousand."
    )}
    memo = "Revenue was $877.4M against optimization costs of $615M."

    report = verify_answer(memo, corpus, computed_values=[], rejected_calcs=[])

    assert report.unverified == []
    assert {f.value for f in report.verified} == {"877.4", "615"}


def test_verify_memo_adds_unbacked_derivations_section():
    memo = "Free cash flow grew 26.2% year over year."
    corpus = "Free cash flow grew 26.2% year over year, per the MD&A."
    rejected = [{
        "value": 26.233,
        "reason": "Rejected: fiscal-period mismatch",
        "expression": "(10874.4 - 8614.518) / 8614.518 * 100",
    }]

    out = verify_memo(memo, corpus, computed_values=[], rejected_calcs=rejected)

    assert "## Unbacked Derivations" in out
    assert "26.2" in out.split("## Unbacked Derivations")[1]
