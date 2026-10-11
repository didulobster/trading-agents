"""calculate can reuse its own passing results.

Found on a 2026-10-11 ACN run. The agent computed FCF per year (thousands
inputs, so calculate returned 10874360000.0 in ones), then fed those results
into a growth-rate call. The guard rejected them — calculate's own output is
deliberately never "retrieved" — so the memo dropped the FCF dollar figures,
and the verifier flagged the 26.2% the agent then derived in one expression
as "unbacked", because the passing retry returned the fraction 0.2623.

A passing result was built only from retrieved, period-checked figures, so
reusing it adds nothing a single expression could not do. A rejected call's
value is not a passing result and stays unusable.
"""

from __future__ import annotations

import pytest

import app.edgar_research.agent.tools as tools
from app.edgar_research.application.citation_verifier import verify_answer


@pytest.fixture(autouse=True)
def _fresh():
    tools.reset_run_provenance()
    yield
    tools.reset_run_provenance()


def _retrieved(value: float, unit: str = "thousands") -> dict:
    tools.record_tool_output(f"FY2025 figure: {value:,}")
    return {"value": value, "label": f"figure {value:.0f}", "fiscal_period": "FY2025",
            "source": "ACN 10-K 2025 §Item 8", "unit": unit}


def _chained(value: float, unit: str = "ones") -> dict:
    return {"value": value, "label": "calculated free cash flow", "fiscal_period": "FY2025",
            "source": "calculate", "unit": unit}


async def _calc(expression: str, *inputs: dict) -> str:
    return await tools._dispatch("calculate", {"expression": expression, "inputs": list(inputs)})


@pytest.mark.anyio
async def test_a_passing_result_can_be_an_input_to_the_next_call():
    fcf_25 = await _calc("11474399 - 600039", _retrieved(11474399), _retrieved(600039))
    fcf_24 = await _calc("9131027 - 516509", _retrieved(9131027), _retrieved(516509))
    assert float(fcf_25.split()[0]) == 10874360000.0
    assert float(fcf_24.split()[0]) == 8614518000.0

    growth = await _calc(
        "(10874360000 - 8614518000) / 8614518000 * 100",
        _chained(10874360000), _chained(8614518000),
    )

    assert "Rejected" not in growth
    assert float(growth.split()[0]) == pytest.approx(26.233, abs=0.001)


@pytest.mark.anyio
async def test_a_reused_result_must_be_declared_at_the_scale_calculate_returned_it():
    """Results are already in ones. Declared as thousands, the next call
    would scale it up a thousandfold."""
    await _calc("11474399 - 600039", _retrieved(11474399), _retrieved(600039))

    result = await _calc("10874360000 / 2", _chained(10874360000, unit="thousands"), _chained(2.0, "ones"))

    assert result.startswith("Rejected")
    assert "ones" in result


@pytest.mark.anyio
async def test_a_rejected_call_s_value_is_still_unusable():
    """No laundering: only a PASSING result counts."""
    _retrieved(30000)                    # a run that has retrieved something
    rejected = await _calc("34000000000 / 2", _chained(34000000000), _chained(2.0))
    assert rejected.startswith("Rejected")

    again = await _calc("34000000000 + 1", _chained(34000000000), _chained(1.0))
    assert again.startswith("Rejected")


@pytest.mark.anyio
async def test_a_converted_result_says_which_unit_it_is_in():
    """The agent read 10874360000.0 from thousands inputs as an error. The
    note has no digits, so it cannot back a memo figure."""
    result = await _calc("11474399 - 600039", _retrieved(11474399), _retrieved(600039))

    note = result[len(result.split()[0]):]
    assert "ones" in note
    assert not any(ch.isdigit() for ch in note)


@pytest.mark.anyio
async def test_a_result_from_unscaled_inputs_carries_no_note():
    """Only conversion earns the note: two billions-scale inputs are still
    converted to ones, but two percents are not."""
    result = await _calc("25.2 - 24.0", _retrieved(25.2, "percent"), _retrieved(24.0, "percent"))
    assert result == str(25.2 - 24.0)


def test_a_percent_stated_from_a_passing_fraction_is_not_flagged():
    """The rejected chained call computed 26.23 (percent); the passing retry
    returned 0.2623 (fraction). The memo's 26.2% is that passing result."""
    report = verify_answer(
        "FCF grew 26.2% in FY2025.",
        {0: "operating cash flow 11,474,399 and 9,131,027"},
        computed_values=[0.2623294768204094],
        rejected_calcs=[{"value": 26.2329, "reason": "Rejected: no tool returned these figures"}],
    )

    assert report.flagged == []
    assert [f.value for f in report.verified if f.kind == "computed"] == ["26.2"]


def test_only_results_gain_a_percent_form_not_memo_figures():
    """A memo's "0.5" is not backed by a computed 50: the percent form
    applies to what calculate returned, not to every number in the memo."""
    report = verify_answer("The ratio was 0.5.", {0: "unrelated 7,777"}, computed_values=[50.0])
    assert [f.value for f in report.verified if f.kind == "computed"] == []


@pytest.mark.anyio
async def test_a_run_that_has_retrieved_nothing_cannot_calculate_with_made_up_figures():
    """Check 4 ran only `if corpus:`, so before the first retrieval of a run
    every declared input passed as "retrieved" — a remembered figure could
    be computed with, and its result then reused as a passing result."""
    result = await _calc("34000000000 / 30000000000", _chained(34000000000), _chained(30000000000))

    assert result.startswith("Rejected")
    assert tools.get_calc_results() == []


# ---------------------------------------------------------------------------
# Found on the 2026-10-11 ACN run after #139/#140
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_an_error_carries_no_unit_note():
    """`Error evaluating '(11474 -  ? )' ... (in ones: ...)` — the note
    describes a number, and an error is not one."""
    result = await _calc("(11474 -  ? )", _retrieved(11474, "millions"))

    assert result.startswith("Error evaluating")
    assert "ones" not in result


@pytest.mark.anyio
async def test_the_unit_note_does_not_call_a_ratio_a_dollar_amount():
    """25.66 was a growth rate; "in ones" read as if it were dollars."""
    result = await _calc("(11474 - 9131) / 9131 * 100", _retrieved(11474, "millions"), _retrieved(9131, "millions"))

    assert "converted to ones before calculating" in result


@pytest.mark.anyio
async def test_a_hand_scaled_expression_is_told_to_use_the_declared_value():
    """The agent declared 34 billions and still wrote 34000000000 in the
    expression; the rejection never said why that could not work."""
    _retrieved(34, "billions")
    _retrieved(30, "billions")
    result = await _calc("(34000000000 - 30000000000) / 30000000000 * 100",
                         _retrieved(34, "billions"), _retrieved(30, "billions"))

    assert result.startswith("Rejected")
    assert "exactly as declared" in result


@pytest.mark.parametrize("memo", [
    "The change was -0.551142522485972%, a decline.",
    "The change was -0.55%, a decline.",
    "Diluted shares declined 0.55%.",
])
def test_a_negative_result_is_recognised_however_the_memo_states_it(memo):
    """The verifier read "-0.55" as "0.55" and matched results only at one or
    two decimals, so every negative calculated figure — and any stated at
    full precision — was listed as unverified."""
    report = verify_answer(memo, {0: "diluted shares 632,435,108 and 635,940,044"},
                           computed_values=[-0.551142522485972])

    assert report.unverified == []
    assert [f.kind for f in report.verified] == ["computed"]
