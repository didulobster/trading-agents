"""The termination proof.

The stated exit criterion — "across 5 test runs, the debate always terminates
within the round cap" — cannot establish a bound. Five clean stochastic runs
are consistent with a 10% runaway rate at roughly 59% probability; that is a
smoke test wearing the clothes of a guarantee.

`next_debate_step` is a pure function of state, so it can be evaluated over
every reachable input in milliseconds at zero API cost. THIS is the test that
closes the termination criterion. The live runs then verify *integration* —
that the router is actually wired to the edges — which is a strictly weaker
claim and worth writing down as such.
"""

from __future__ import annotations

import pytest

from app.agent.trading.application.debate_router import (
    MAX_ROUNDS,
    MAX_TURNS,
    UNPRODUCTIVE_STOP,
    next_debate_step,
    termination_reason,
)
from app.agent.trading.domain.debate import DebateClaim, DebateTurn, DebateTurnPayload


def _stub_turn(index: int, productive: bool = True) -> DebateTurn:
    return DebateTurn(
        turn_index=index,
        round_num=(index // 2) + 1,
        side="bull" if index % 2 == 0 else "bear",
        payload=DebateTurnPayload(
            stance="hold",
            argument="stub",
            claims=[
                DebateClaim(
                    claim_id=f"c{index}" if productive else "c0",
                    text="stub",
                    evidence_ref="none",
                )
            ],
        ),
        productive=productive,
    )


def _state(n: int, productive: bool = True, **extra) -> dict:
    state = {"debate_turns": [_stub_turn(i, productive) for i in range(n)]}
    # evidence present unless a test says otherwise, so the no-evidence
    # short-circuit doesn't quietly answer questions about the cap
    state.setdefault("fundamentals_report", object())
    state.update(extra)
    return state


# ---------------------------------------------------------------------------
# Exhaustive: every reachable turn count, plus five past the cap
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", range(0, MAX_TURNS + 5))
def test_router_alternates_below_the_cap_and_stops_at_or_above_it(n):
    step = next_debate_step(_state(n))
    if n >= MAX_TURNS:
        assert step == "done"
    else:
        assert step == ("bull" if n % 2 == 0 else "bear")


def test_router_cap_beats_productivity():
    """The cap wins even when every turn introduced a new claim.

    Ordering inside the router is load-bearing: the cap check is first and
    cannot raise, so a malformed turn record cannot make control fall through
    to the alternation branch and loop forever.
    """
    assert next_debate_step(_state(MAX_TURNS, productive=True)) == "done"


def test_max_turns_is_derived_from_max_rounds():
    """Guards the recursion_limit the CLI derives from MAX_ROUNDS."""
    assert MAX_TURNS == 2 * MAX_ROUNDS


# ---------------------------------------------------------------------------
# The other two exits
# ---------------------------------------------------------------------------

def test_router_stops_on_two_consecutive_unproductive_turns():
    state = _state(UNPRODUCTIVE_STOP, productive=False)
    assert next_debate_step(state) == "done"


def test_router_continues_when_only_the_last_turn_was_unproductive():
    """One side repeating itself is a bad turn; both sides repeating
    themselves is the end of the argument."""
    turns = [_stub_turn(0, productive=True), _stub_turn(1, productive=False)]
    state = {"debate_turns": turns, "fundamentals_report": object()}
    assert next_debate_step(state) == "bull"


def test_router_ignores_unproductive_turns_earlier_in_the_transcript():
    turns = [
        _stub_turn(0, productive=False),
        _stub_turn(1, productive=False),
        _stub_turn(2, productive=True),
        _stub_turn(3, productive=True),
    ]
    state = {"debate_turns": turns, "fundamentals_report": object()}
    assert next_debate_step(state) == "bull"


def test_router_skips_the_debate_when_no_analyst_ran():
    """A --only run that excluded every analyst leg would otherwise produce a
    debate over an empty pack: two models arguing from nothing, which reads
    like a debate and is theatre."""
    assert next_debate_step({}) == "done"
    assert next_debate_step({"debate_turns": []}) == "done"


@pytest.mark.parametrize(
    "key", ["fundamentals_report", "technical_report", "news_digest"]
)
def test_router_opens_with_bull_when_any_analyst_output_is_present(key):
    assert next_debate_step({key: object()}) == "bull"


def test_no_evidence_check_only_applies_on_the_opening_turn():
    """Once turns exist the pack question is settled; re-asking it mid-debate
    would end a live debate the moment a report was read out of state under a
    different key."""
    state = {"debate_turns": [_stub_turn(0)]}   # no analyst outputs at all
    assert next_debate_step(state) == "bear"


# ---------------------------------------------------------------------------
# termination_reason
# ---------------------------------------------------------------------------

def test_termination_reason_reports_the_cap():
    assert termination_reason(_state(MAX_TURNS)) == "round_cap"


def test_termination_reason_reports_no_evidence():
    assert termination_reason({}) == "no_evidence"


def test_termination_reason_reports_unproductive():
    assert termination_reason(_state(UNPRODUCTIVE_STOP, productive=False)) == "unproductive"


def test_every_done_state_has_a_reason():
    """No exit path leaves debate_terminated_by empty — an unrecorded reason
    would read in the memo as a debate that simply ended."""
    states = [{}, _state(MAX_TURNS), _state(UNPRODUCTIVE_STOP, productive=False)]
    for state in states:
        assert next_debate_step(state) == "done"
        assert termination_reason(state) in {
            "round_cap",
            "unproductive",
            "no_evidence",
        }
