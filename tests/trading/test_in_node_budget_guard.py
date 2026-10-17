"""The run budget and deadline, applied INSIDE the nodes that make many calls.

`check_run_guards` ran only on graph edges, so the fundamentals node — up to
LOOP_MAX_TURNS model calls plus every server-side call its tools make — and
the synthesizer's extra verdict samples (each a fresh 9-turn risk panel plus
two synthesis calls) spent unseen until the node returned. The CLI's own
comment conceded it: "the run-level guards can only fire between nodes,
which on this graph means after the fundamentals stage has already been
paid for." These pin the in-node checks.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.shared.cost import UsageSummary
import app.trading.application.nodes as nodes
import app.trading.infrastructure.fundamentals_port as port
from app.trading.domain.budget import CostEvent, RunBudget
from app.trading.domain.decision_memo import Verdict
from app.edgar_research.fundamentals_memo import Spend

from tests.trading.test_risk_verdict_sampling import (
    _memo,
    _state,
    _stub_extra_panel_samples,
    _stub_synthesis_sequence,
)


@pytest.fixture(autouse=True)
def _three_verdict_samples(monkeypatch):
    """These scenarios are written as 3-sample votes. Pinned so they keep
    testing what they say when the production sample count changes."""
    monkeypatch.setattr(nodes, "RISK_VERDICT_SAMPLES", 3)


def _event(usd: float, event_id: str = "earlier:1") -> CostEvent:
    return CostEvent(
        event_id=event_id, node="earlier", model="m", input_tokens=0, output_tokens=0,
        cache_creation_input_tokens=0, cache_read_input_tokens=0, usd=usd,
    )


def _budget(max_usd: float = 1.0, *, minutes: float = 30) -> RunBudget:
    return RunBudget(
        max_usd=max_usd, deadline_utc=datetime.now(timezone.utc) + timedelta(minutes=minutes)
    )


# ---------------------------------------------------------------------------
# fundamentals_port.budget_stop_check
# ---------------------------------------------------------------------------

def _spend(usd: float) -> Spend:
    return Spend(model="m", usage=UsageSummary(), usd=usd)


def test_no_budget_means_no_check():
    assert port.budget_stop_check(None) is None


def test_under_budget_the_check_passes():
    check = port.budget_stop_check(_budget(1.0), [_event(0.10)])
    assert check(_spend(0.01)) is None


def test_in_flight_spend_counts_against_the_run_s_earlier_events():
    """The memo run's spend so far (its tools' server-side calls included,
    priced inside EDGAR Research) is added to what the run already spent."""
    under = port.budget_stop_check(_budget(1.0), [_event(0.50)])
    over = port.budget_stop_check(_budget(1.0), [_event(0.60)])

    assert under(_spend(0.44)) is None                   # 0.50 + 0.44 < 1.00
    reason = over(_spend(0.44))                          # 0.60 + 0.44 >= 1.00
    assert reason.startswith("budget_exceeded")
    assert "$1.00 run budget" in reason


def test_a_passed_deadline_stops_the_loop():
    check = port.budget_stop_check(_budget(10.0, minutes=-1))
    assert check(_spend(0.0)).startswith("deadline_exceeded")


@pytest.mark.anyio
async def test_the_fundamentals_node_hands_the_port_its_budget_and_prior_spend(monkeypatch):
    seen = {}

    async def fake_report(ticker, as_of=None, run_id=None, **kwargs):
        seen["as_of"] = as_of
        seen.update(kwargs)
        return None

    monkeypatch.setattr(nodes, "get_fundamentals_report", fake_report)
    budget, prior = _budget(0.75), [_event(0.05)]

    as_of = date(2026, 8, 19)
    await nodes.fundamentals_node(
        {"ticker": "ACN", "as_of_date": as_of, "budget": budget, "cost_events": prior}
    )

    # The analysis date rides with the budget: the node cannot pass one and
    # forget the other.
    assert seen == {"as_of": as_of, "budget": budget, "prior_events": prior}


# ---------------------------------------------------------------------------
# synthesizer_node's extra samples
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_extra_verdict_samples_are_skipped_once_the_budget_is_spent(monkeypatch):
    _stub_extra_panel_samples(monkeypatch)
    first = _memo("ACN", Verdict.HOLD, tag="a").model_copy(
        update={"cost_events": [_event(0.06, "synthesis:1")]}
    )
    _stub_synthesis_sequence(monkeypatch, [first, _memo("ACN", Verdict.SELL, tag="b")])

    # 0.05 before the node + 0.06 for sample 1 = 0.11 >= 0.10
    state = _state(budget=_budget(0.10), cost_events=[_event(0.05)])
    memo = (await nodes.synthesizer_node(state))["decision_memo"]

    assert memo.verdict_samples == ["hold"]
    assert any("2 of 3 risk-verdict sample(s) were skipped" in g for g in memo.data_gaps)
    assert any("budget exceeded" in g for g in memo.data_gaps)


@pytest.mark.anyio
async def test_under_budget_all_samples_still_run(monkeypatch):
    _stub_extra_panel_samples(monkeypatch)
    _stub_synthesis_sequence(monkeypatch, [
        _memo("ACN", Verdict.HOLD, tag="a"),
        _memo("ACN", Verdict.SELL, tag="b"),
        _memo("ACN", Verdict.HOLD, tag="c"),
    ])

    memo = (await nodes.synthesizer_node(_state(budget=_budget(5.0))))["decision_memo"]

    assert memo.verdict_samples == ["hold", "sell", "hold"]
    assert not any("skipped" in g for g in memo.data_gaps)


@pytest.fixture
def anyio_backend():
    return "asyncio"
