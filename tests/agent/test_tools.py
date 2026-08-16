from app.agent.tools import (
    reset_run_provenance,
    record_tool_output,
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
             "source": "V 10-K 2023 §Item 8"},
            {"value": 21.0, "label": "FY2023 operating income", "fiscal_period": "FY2023",
             "source": "V 10-K 2023 §Item 7"},
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
             "source": "V 10-K 2025 §Item 8"},
            {"value": 24.0, "label": "FY2025 operating income", "fiscal_period": "FY2025",
             "source": "V 10-K 2025 §Item 7"},
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
             "source": "V 10-K §Item 8"},
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
          "source": "X 10-K 2025"}],
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
             "source": "V 10-K 2025 §Item 8"},
        ],
    )

    assert err is None
