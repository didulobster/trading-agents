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
