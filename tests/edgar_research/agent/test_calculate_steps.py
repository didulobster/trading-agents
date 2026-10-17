"""calculate records the sums inside an expression, for the memo verifier.

Found on a 2026-10-17 ACN memo. The agent computed the buyback-to-M&A ratio
as one expression, "(7520965+4619497+4524646)/(4940884+1471255+6582702)",
then wrote both three-year totals ($16.67B and $12.99B) in the memo. Only
the final ratio was recorded, so both totals were flagged unverified though
calculate had computed them.
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


def _retrieved(value: float) -> dict:
    tools.record_tool_output(f"FY2026 figure: {value:,.0f}")
    return {"value": value, "label": f"figure {value:.0f}", "fiscal_period": "FY2026",
            "source": "ACN 10-K 2026 §Item 8", "unit": "thousands"}


RATIO = "(7520965+4619497+4524646)/(4940884+1471255+6582702)"
FIGURES = (7520965, 4619497, 4524646, 4940884, 1471255, 6582702)


def test_steps_are_every_inner_operation_in_input_units():
    steps = tools.calc_steps("(1+2)*(3+4)", [])
    assert sorted(steps) == [3.0, 7.0]


def test_steps_apply_declared_units():
    steps = tools.calc_steps("(2+3)/5", [{"value": 2, "unit": "thousands"}, {"value": 3, "unit": "thousands"}])
    assert steps == [5000.0]


@pytest.mark.anyio
async def test_a_passing_call_records_its_steps_but_not_as_results():
    await tools._dispatch("calculate", {"expression": RATIO, "inputs": [_retrieved(v) for v in FIGURES]})
    assert 16665108000.0 in tools.get_calc_steps()
    assert 12994841000.0 in tools.get_calc_steps()
    # Steps never become reusable calculate inputs.
    assert 16665108000.0 not in tools.get_calc_results()


@pytest.mark.anyio
async def test_the_memo_totals_verify_against_the_steps():
    await tools._dispatch("calculate", {"expression": RATIO, "inputs": [_retrieved(v) for v in FIGURES]})
    memo = "Over three years repurchases totaled $16.67B against $12.99B of acquisitions, a ratio of 1.28x."
    without = verify_answer(memo, {0: ""}, computed_values=tools.get_calc_results())
    with_steps = verify_answer(memo, {0: ""}, computed_values=tools.get_calc_results() + tools.get_calc_steps())
    assert {f.value for f in without.unverified} == {"16.67", "12.99"}
    assert not with_steps.unverified


@pytest.mark.anyio
async def test_a_rejected_call_records_no_steps():
    # 999 is not a retrieved figure, so the guard rejects the call.
    await tools._dispatch("calculate", {"expression": "(999+1)/2", "inputs": [
        {"value": 999, "label": "x", "fiscal_period": "FY2026", "source": "memory", "unit": "ones"},
        {"value": 1, "label": "y", "fiscal_period": "FY2026", "source": "memory", "unit": "ones"},
    ]})
    assert tools.get_calc_steps() == []
