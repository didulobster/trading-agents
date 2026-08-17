import asyncio

import pytest

import app.agent.tools as tools_module
from app.agent.tools import (
    execute_tool,
    get_provenance_corpus,
    reset_run_provenance,
    record_tool_output,
    record_calc_result,
    record_rejected_calc,
    get_unretried_rejected_calcs,
    safe_calculate,
    validate_calculate_inputs,
)


def setup_function():
    reset_run_provenance()


def test_reproduces_reported_cross_fiscal_year_mismatch():
    """Reproduces the exact reported bug: FY2025's debt figure ($25.2B)
    retrieved correctly, then declared as FY2023's input when computing a
    'FY2023' leverage ratio. Check 3 alone passes this (25.2 really was
    retrieved this run) — check 4 must catch the period mismatch."""
    record_tool_output(
        "For the fiscal year ended September 30, 2025 (FY2025), total debt "
        "was $25.2 billion. [V 10-K 2025 §Item 8]"
    )
    record_tool_output(
        "For the fiscal year ended September 30, 2023 (FY2023), operating "
        "income was $21.0 billion. [V 10-K 2023 §Item 7]"
    )

    err = validate_calculate_inputs(
        "25.2 / 21.0",
        [
            {"value": 25.2, "label": "FY2023 debt", "fiscal_period": "FY2023",
             "source": "V 10-K 2023 §Item 8", "unit": "billions"},
            {"value": 21.0, "label": "FY2023 operating income", "fiscal_period": "FY2023",
             "source": "V 10-K 2023 §Item 7", "unit": "billions"},
        ],
    )

    assert err is not None
    assert "fiscal-period mismatch" in err
    assert "25.2" in err
    assert "2023" in err


def test_correct_fiscal_period_pairing_passes():
    """The same value, correctly labeled for the period it was actually
    retrieved under, must not be rejected."""
    record_tool_output(
        "For the fiscal year ended September 30, 2025 (FY2025), total debt "
        "was $25.2 billion. [V 10-K 2025 §Item 8]"
    )
    record_tool_output(
        "For the fiscal year ended September 30, 2025 (FY2025), operating "
        "income was $24.0 billion. [V 10-K 2025 §Item 7]"
    )

    err = validate_calculate_inputs(
        "25.2 / 24.0",
        [
            {"value": 25.2, "label": "FY2025 debt", "fiscal_period": "FY2025",
             "source": "V 10-K 2025 §Item 8", "unit": "billions"},
            {"value": 24.0, "label": "FY2025 operating income", "fiscal_period": "FY2025",
             "source": "V 10-K 2025 §Item 7", "unit": "billions"},
        ],
    )

    assert err is None


def test_unparseable_fiscal_period_skips_check_rather_than_reject():
    """A fiscal_period with no extractable year (rare, but the schema
    doesn't enforce format) fails open rather than blocking a legitimate
    calculation — we can't check what we can't parse."""
    record_tool_output("Total debt was $25.2 billion. [V 10-K §Item 8]")

    err = validate_calculate_inputs(
        "25.2 * 2",
        [
            {"value": 25.2, "label": "debt", "fiscal_period": "most recent annual filing",
             "source": "V 10-K §Item 8", "unit": "billions"},
        ],
    )

    assert err is None


def test_documents_false_positive_risk_when_period_stated_far_from_value():
    """Documents a known, accepted tradeoff: the proximity window is finite
    (400 chars), so a legitimate value whose period is stated far away in
    the same tool output (e.g. mentioned once at the top of a long answer,
    not restated near the number itself) would be wrongly rejected. In
    practice, filing-derived prose usually restates the period close to any
    cited figure (see test_correct_fiscal_period_pairing_passes and the
    multi-year-listing case), so this should be rare — but it is a real
    false-positive surface, not a hypothetical. The cost of hitting it is
    low: the agent just re-retrieves the figure with the period stated
    nearby and retries. This test exists so the boundary is asserted, not
    just described in a comment."""
    record_tool_output(
        "For the fiscal year ended December 31, 2025 (FY2025), the company "
        "reported strong results across all segments. " + "x" * 420 +
        " Total debt outstanding at year end was 25200."
    )

    err = validate_calculate_inputs(
        "25200 * 2",
        [{"value": 25200, "label": "debt", "fiscal_period": "FY2025",
          "source": "X 10-K 2025", "unit": "millions"}],
    )

    assert err is not None
    assert "fiscal-period mismatch" in err


def test_value_retrieved_multiple_times_passes_if_any_occurrence_matches():
    """A value appearing near several years in different tool outputs (e.g.
    quoted once in a YoY comparison, once standalone) should pass as long as
    at least one occurrence is near the declared period — not require every
    occurrence to match."""
    record_tool_output(
        "FY2025 debt of $25.2 billion compares to FY2024's lower balance. "
        "[V 10-K 2025 §Item 8]"
    )
    record_tool_output(
        "As of September 30, 2025, total debt stood at $25.2 billion. "
        "[V 10-K 2025 §Item 8]"
    )

    err = validate_calculate_inputs(
        "25.2 * 2",
        [
            {"value": 25.2, "label": "FY2025 debt", "fiscal_period": "FY2025",
             "source": "V 10-K 2025 §Item 8", "unit": "billions"},
        ],
    )

    assert err is None


def test_missing_unit_is_rejected():
    """Every declared input must state the scale it's reported at — a
    figure retrieved without a unit is exactly the gap that let a
    thousands-scale figure get divided by a millions-scale figure with
    nothing to catch it."""
    record_tool_output("Total debt was $25.2 billion. [V 10-K 2025 §Item 8]")

    err = validate_calculate_inputs(
        "25.2 * 2",
        [{"value": 25.2, "label": "FY2025 debt", "fiscal_period": "FY2025",
          "source": "V 10-K 2025 §Item 8"}],
    )

    assert err is not None
    assert "unit" in err


def test_invalid_unit_is_rejected():
    record_tool_output("Total debt was $25.2 billion. [V 10-K 2025 §Item 8]")

    err = validate_calculate_inputs(
        "25.2 * 2",
        [{"value": 25.2, "label": "FY2025 debt", "fiscal_period": "FY2025",
          "source": "V 10-K 2025 §Item 8", "unit": "billion dollars"}],
    )

    assert err is not None
    assert "unit" in err


def test_reproduces_reported_acn_leverage_units_bug():
    """Reproduces the reported ACN run: current debt ($114,484 thousand)
    and noncurrent debt ($5,034,169 thousand) retrieved from the balance
    sheet, operating income ($10,226 million) retrieved from the segment
    table — both individually real and correctly attributed to FY2025, but
    at mismatched scales. Without normalization the raw literals produce
    503.486x; the correct leverage is ~0.50x. validate_calculate_inputs
    must accept the call (every check besides units already passes), and
    safe_calculate must apply the declared units rather than the model
    doing the thousands->millions conversion by hand."""
    record_tool_output(
        "As of the FY2025 balance sheet date, current portion of long-term "
        "debt was $114,484 thousand. [ACN 10-K 2025 §Item 8]"
    )
    record_tool_output(
        "As of the FY2025 balance sheet date, long-term debt was "
        "$5,034,169 thousand. [ACN 10-K 2025 §Item 8]"
    )
    record_tool_output(
        "FY2025 operating income by segment totaled $10,226 million. "
        "[ACN 10-K 2025 §Item 7]"
    )

    expression = "(114484 + 5034169) / 10226"
    inputs = [
        {"value": 114484, "label": "current portion of long-term debt",
         "fiscal_period": "FY2025", "source": "ACN 10-K 2025 §Item 8",
         "unit": "thousands"},
        {"value": 5034169, "label": "long-term debt",
         "fiscal_period": "FY2025", "source": "ACN 10-K 2025 §Item 8",
         "unit": "thousands"},
        {"value": 10226, "label": "operating income",
         "fiscal_period": "FY2025", "source": "ACN 10-K 2025 §Item 7",
         "unit": "millions"},
    ]

    assert validate_calculate_inputs(expression, inputs) is None

    result = float(safe_calculate(expression, inputs))
    assert result == pytest.approx(0.5035, abs=0.001)


def test_same_unit_inputs_are_unaffected_by_normalization():
    """Two figures declared in the same unit must produce the same result
    as before units existed — normalization should be a no-op when scales
    already match."""
    record_tool_output("FY2025 debt was $25.2 billion. [V 10-K 2025 §Item 8]")
    record_tool_output(
        "FY2025 operating income was $24.0 billion. [V 10-K 2025 §Item 7]"
    )

    expression = "25.2 / 24.0"
    inputs = [
        {"value": 25.2, "label": "FY2025 debt", "fiscal_period": "FY2025",
         "source": "V 10-K 2025 §Item 8", "unit": "billions"},
        {"value": 24.0, "label": "FY2025 operating income", "fiscal_period": "FY2025",
         "source": "V 10-K 2025 §Item 7", "unit": "billions"},
    ]

    result = float(safe_calculate(expression, inputs))
    assert result == pytest.approx(25.2 / 24.0, abs=1e-9)


def test_rejected_calc_surfaces_as_unretried_if_never_retried():
    """Reproduces the reported ACN FCF gap: a calculate() call rejected for
    fiscal-period mismatch, whose result the model then used in the memo
    anyway without ever making a passing call. The would-be result must
    surface via get_unretried_rejected_calcs() so the memo verifier has a
    chance to flag it, even though citation_verifier alone would pass it
    (the raw FCF figures are legitimately retrieved text)."""
    expression = "(10874.4 - 8614.518) / 8614.518 * 100"
    inputs = [
        {"value": 10874.4, "label": "FY2025 FCF", "fiscal_period": "FY2025",
         "source": "ACN 10-K 2025", "unit": "millions"},
        {"value": 8614.518, "label": "FY2023 FCF", "fiscal_period": "FY2025",
         "source": "ACN 10-K 2025", "unit": "millions"},
    ]
    record_rejected_calc(expression, inputs, "Rejected: fiscal-period mismatch")

    unretried = get_unretried_rejected_calcs()
    assert len(unretried) == 1
    assert unretried[0]["value"] == pytest.approx(26.233, abs=0.001)


def test_rejected_calc_dropped_once_successfully_retried():
    """The same derivation, later backed by a passing calculate() call with
    correctly labeled inputs, must no longer be reported as unretried —
    the model did the right thing on retry."""
    expression = "(10874.4 - 8614.518) / 8614.518 * 100"
    inputs = [
        {"value": 10874.4, "label": "FY2025 FCF", "fiscal_period": "FY2025",
         "source": "ACN 10-K 2025", "unit": "millions"},
        {"value": 8614.518, "label": "FY2023 FCF", "fiscal_period": "FY2025",
         "source": "ACN 10-K 2025", "unit": "millions"},
    ]
    record_rejected_calc(expression, inputs, "Rejected: fiscal-period mismatch")
    record_calc_result(safe_calculate(expression, inputs))

    assert get_unretried_rejected_calcs() == []


def test_similarity_scores_are_stripped_from_provenance(monkeypatch):
    """ask_edgar citation lines carry retrieval diagnostics (sim=0.516)
    that are not filing figures. Recorded verbatim, every sim score became
    a corpus number the verifier's scale fallback could match a fabricated
    memo figure against ($516.5M / 1000 ≈ sim=0.516 — the exact mechanism
    behind a reported run's invented capex column). The scores must be
    stripped before the output enters the provenance corpus; the model
    still sees them in the raw tool result."""
    async def fake_dispatch(name, inputs):
        return (
            "Revenue was $64,896 million. [ACN 10-K 2025 §Item 7]\n"
            "Sources:\n  [ACN 10-K 2025 §Item 7] sim=0.516\n"
            "  [ACN 10-K 2025 §Item 8] sim=0.528"
        )

    monkeypatch.setattr(tools_module, "_dispatch", fake_dispatch)
    result = asyncio.run(execute_tool("ask_edgar", {"question": "revenue?"}))

    assert "sim=0.516" in result  # model still sees the scores
    corpus = get_provenance_corpus()
    assert "0.516" not in corpus and "0.528" not in corpus
    assert "64,896" in corpus  # the actual figures are still recorded
