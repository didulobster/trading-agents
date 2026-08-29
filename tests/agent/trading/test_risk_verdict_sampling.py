"""Majority-of-N risk verdict sampling (added 2026-08-26, code review).

Post-fix determinism measurement on two tickers (AVGO, ASML — see
trading-agent-known-gaps.md) showed the risk panel's verdict genuinely
splits direction across independent samples of the same fixed debate, and a
fixed-ledger repeat of the Risk Judge alone came back unanimous — which
localizes the variance to the PANEL, not the Judge. `synthesizer_node` now
samples the whole (panel, Research Manager, Risk Judge) trial
`RISK_VERDICT_SAMPLES` times and reports the majority verdict, or
`Verdict.UNRESOLVED` when there is no majority — rather than reporting
whichever single trial happened to run.

These tests exercise `synthesizer_node` directly (not the full graph),
monkeypatching the same two seams the existing debate/checkpoint graph
tests already use: `risk_nodes.run_risk_turn` for the extra panel samples,
`nodes.run_synthesis` for the LLM synthesis call — so no network call
happens and the sample-to-sample content is fully controlled.
"""

from __future__ import annotations

from datetime import date

import pytest

import app.agent.trading.application.nodes as nodes
import app.agent.trading.application.risk_nodes as risk_nodes
from app.agent.trading.domain.decision_memo import DecisionMemo, Verdict
from app.agent.trading.domain.risk import (
    PERSONAS,
    RiskFactor,
    RiskTurn,
    RiskTurnPayload,
)
from app.agent.trading.infrastructure.synthesis_port import (
    MemoVerificationError,
    SynthesisFabricationError,
    SynthesisReferenceError,
)

AS_OF = date(2026, 8, 22)


def _turn(turn_index: int, persona: str, *, propose: bool = False) -> RiskTurn:
    """One risk turn. `propose=True` on turn 0 only, matching how a real
    panel's slate is built — enough for `build_risk_ledger` to return a
    non-empty ledger, which is what makes `synthesizer_node` decide there
    is something to sample in the first place."""
    proposes = (
        [
            RiskFactor(
                factor_id="RF0001",
                text="a risk",
                trigger="a level",
                horizon="weeks",
                evidence_ref="none",
                evidence_quote="none",
            )
        ]
        if propose
        else []
    )
    return RiskTurn(
        turn_index=turn_index,
        round_num=(turn_index // len(PERSONAS)) + 1,
        persona=persona,
        payload=RiskTurnPayload(proposes=proposes, argument=f"{persona} {turn_index}"),
        estimated_cost_usd=0.01,
    )


def _panel() -> list[RiskTurn]:
    return [
        _turn(i, PERSONAS[i % len(PERSONAS)], propose=(i == 0))
        for i in range(9)
    ]


def _state(**over) -> dict:
    state = {"ticker": "ACN", "as_of_date": AS_OF, "risk_turns": _panel()}
    state.update(over)
    return state


def _memo(
    ticker: str,
    verdict: Verdict | str,
    *,
    tag: str,
    data_gaps=None,
    reasoning="stub reasoning",
    confidence: float = 0.5,
) -> DecisionMemo:
    return DecisionMemo(
        ticker=ticker,
        bull_case=f"bull [{tag}]",
        bear_case="stub bear",
        research_thesis="stub thesis",
        risk_debate_summary="stub risk narrative",
        technical_signal="NOT RUN",
        reasoning=reasoning,
        watch_items=[],
        verdict=verdict,
        confidence=confidence,
        data_as_of_date=AS_OF,
        data_gaps=list(data_gaps or []),
        assumptions=[],
        evidence=[],
    )


def _stub_extra_panel_samples(monkeypatch):
    """The 2 extra samples `_sample_additional_risk_panel` generates go
    through `risk_nodes._risk_turn` -> the module-level `run_risk_turn`
    name in `risk_nodes` — same seam `test_debate_graph.py` patches."""

    async def fake_turn(state, persona, turn_index):
        return _turn(turn_index, persona, propose=(turn_index == 0))

    monkeypatch.setattr(risk_nodes, "run_risk_turn", fake_turn)


def _stub_synthesis_sequence(monkeypatch, memos: list[DecisionMemo]):
    """Returns memos[0], memos[1], memos[2], ... in call order — one call
    per sample, regardless of what ledger/state it was given."""
    calls = iter(memos)

    async def fake_run_synthesis(state, *, ledger, base_gaps, base_evidence, as_of, client=None):
        return next(calls)

    monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)


@pytest.mark.anyio
async def test_no_risk_panel_means_no_sampling_at_all(monkeypatch):
    """`--only technical` (or any run where the risk panel never ran):
    `_risk_caveats` returns an empty ledger, and the single `run_synthesis`
    call's memo passes through unchanged — no extra panel samples, no
    `verdict_samples`, matching the pre-sampling behavior exactly."""
    calls = 0

    async def fake_run_synthesis(state, *, ledger, base_gaps, base_evidence, as_of, client=None):
        nonlocal calls
        calls += 1
        return _memo("ACN", Verdict.HOLD, tag="only")

    monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)

    memo = (await nodes.synthesizer_node(_state(risk_turns=[])))["decision_memo"]

    assert calls == 1
    assert memo.verdict == Verdict.HOLD
    assert memo.verdict_samples == []


@pytest.mark.anyio
async def test_a_majority_verdict_is_taken_from_a_sample_that_actually_agrees_with_it(monkeypatch):
    """hold/sell/hold splits 2-1 for hold. The final memo must be the
    sample that itself said hold (not sample 1 relabeled) — otherwise the
    memo's narrative (bull_case, reasoning, ...) would argue one thing
    while the verdict field said another."""
    _stub_extra_panel_samples(monkeypatch)
    _stub_synthesis_sequence(monkeypatch, [
        _memo("ACN", Verdict.HOLD, tag="a"),
        _memo("ACN", Verdict.SELL, tag="b"),
        _memo("ACN", Verdict.HOLD, tag="c"),
    ])

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.verdict == Verdict.HOLD
    assert memo.verdict_samples == ["hold", "sell", "hold"]
    # sample 1 said hold too, and is first in generation order — it's the
    # one whose narrative should have been kept
    assert memo.bull_case == "bull [a]"
    assert any("majority hold" in g for g in memo.data_gaps)


@pytest.mark.anyio
async def test_three_way_split_is_reported_as_unresolved_not_as_one_samples_guess(monkeypatch):
    """buy/sell/hold: no verdict has more than 1 of 3 votes. Reporting any
    single one of them as THE verdict would misrepresent a result that
    doesn't actually have a majority — that's the whole reason
    `Verdict.UNRESOLVED` exists."""
    _stub_extra_panel_samples(monkeypatch)
    _stub_synthesis_sequence(monkeypatch, [
        _memo("ACN", Verdict.BUY, tag="a"),
        _memo("ACN", Verdict.SELL, tag="b"),
        _memo("ACN", Verdict.HOLD, tag="c"),
    ])

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.verdict == Verdict.UNRESOLVED
    assert memo.verdict_samples == ["buy", "sell", "hold"]
    assert any("no majority" in g for g in memo.data_gaps)


@pytest.mark.anyio
async def test_unanimous_verdict_is_reported_as_a_majority_with_no_special_casing(monkeypatch):
    _stub_extra_panel_samples(monkeypatch)
    _stub_synthesis_sequence(monkeypatch, [
        _memo("ACN", Verdict.SELL, tag="a"),
        _memo("ACN", Verdict.SELL, tag="b"),
        _memo("ACN", Verdict.SELL, tag="c"),
    ])

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.verdict == Verdict.SELL
    assert memo.verdict_samples == ["sell", "sell", "sell"]


@pytest.mark.anyio
async def test_sampling_runs_exactly_risk_verdict_samples_total_trials(monkeypatch):
    """RISK_VERDICT_SAMPLES is 3: the graph-checkpointed sample plus 2 more,
    not 3 more (which would silently make live runs even more expensive
    than intended)."""
    _stub_extra_panel_samples(monkeypatch)
    call_count = 0

    async def fake_run_synthesis(state, *, ledger, base_gaps, base_evidence, as_of, client=None):
        nonlocal call_count
        call_count += 1
        return _memo("ACN", Verdict.HOLD, tag="abc"[call_count - 1])

    monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)

    await nodes.synthesizer_node(_state())

    assert call_count == nodes.RISK_VERDICT_SAMPLES == 3


# ---------------------------------------------------------------------------
# A trial's citation/fabrication guard tripping must not crash the whole
# node — measured live hit rate is ~1-in-8 Risk Judge calls (FIG,
# trading-agent-known-gaps.md, 2026-08-26), which gave a 3-sample run
# better-than-even odds of aborting with no memo at all, discarding every
# trial already paid for.
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_a_guard_dropped_sample_is_excluded_from_the_vote_not_a_crash(monkeypatch):
    """sample 2 trips the fabrication guard; samples 1 and 3 both say hold.
    The run must still produce a memo — the majority of the SURVIVING
    samples, not a crash — and must say honestly that a sample was
    dropped."""
    _stub_extra_panel_samples(monkeypatch)
    calls = iter([
        _memo("ACN", Verdict.HOLD, tag="a"),
        SynthesisFabricationError("unbacked number(s) in reasoning: ['5']"),
        _memo("ACN", Verdict.HOLD, tag="c"),
    ])

    async def fake_run_synthesis(state, *, ledger, base_gaps, base_evidence, as_of, client=None):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.verdict == Verdict.HOLD
    assert memo.verdict_samples == ["hold", "hold"]
    assert any("dropped by the citation/fabrication guard" in g for g in memo.data_gaps)
    assert any("1 of 3" in g for g in memo.data_gaps)


@pytest.mark.anyio
async def test_a_dropped_reference_error_sample_is_also_excluded_not_fatal(monkeypatch):
    """SynthesisReferenceError (unresolved [C:id]/[RFnn] citation after the
    in-call retry) is a per-trial data-quality failure exactly like the
    fabrication guard — same drop-and-continue treatment, not a crash."""
    _stub_extra_panel_samples(monkeypatch)
    calls = iter([
        _memo("ACN", Verdict.SELL, tag="a"),
        _memo("ACN", Verdict.SELL, tag="b"),
        SynthesisReferenceError("still cites unresolved reference(s): ['RF99']"),
    ])

    async def fake_run_synthesis(state, *, ledger, base_gaps, base_evidence, as_of, client=None):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.verdict == Verdict.SELL
    assert memo.verdict_samples == ["sell", "sell"]


@pytest.mark.anyio
async def test_all_samples_dropped_by_the_guard_raises_one_clear_aggregate_error(monkeypatch):
    """If every trial is dropped there is genuinely no memo to return — this
    must still raise, but with one message naming all the failures, not
    just whichever trial happened to run last."""
    _stub_extra_panel_samples(monkeypatch)

    async def fake_run_synthesis(state, *, ledger, base_gaps, base_evidence, as_of, client=None):
        raise SynthesisFabricationError("unbacked number(s): ['5']")

    monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)

    with pytest.raises(SynthesisFabricationError, match="all 3 risk-verdict samples"):
        await nodes.synthesizer_node(_state())


# ---------------------------------------------------------------------------
# Phase 7: synthesizer_node runs an independent post-hoc check over the
# memo it's about to return, distinct from the per-call guards inside
# run_synthesis (which these tests bypass entirely via the monkeypatched
# fake). A memo that slips a fabricated number past the (faked) generation
# path must still be caught here.
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_no_panel_memo_that_fails_post_hoc_verification_raises(monkeypatch):
    # save_failed_decision_memo does real file I/O (see
    # test_vault_run_folder.py for that behavior) — stubbed here so this
    # test stays focused on the raise/routing behavior.
    monkeypatch.setattr(nodes, "save_failed_decision_memo", lambda *a, **k: "stub-path")

    async def fake_run_synthesis(state, *, ledger, base_gaps, base_evidence, as_of, client=None):
        return _memo("ACN", Verdict.HOLD, tag="only", reasoning="Margin could reach 91.4%.")

    monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)

    with pytest.raises(MemoVerificationError, match="91.4"):
        await nodes.synthesizer_node(_state(risk_turns=[]))


@pytest.mark.anyio
async def test_the_chosen_samples_verification_failure_raises_even_with_a_majority(monkeypatch):
    """All three samples agree (hold), so voting alone would happily return
    sample 1 — but sample 1 itself carries a fabricated number, and the
    post-hoc check runs against the SAME trial the chosen memo came from."""
    monkeypatch.setattr(nodes, "save_failed_decision_memo", lambda *a, **k: "stub-path")
    _stub_extra_panel_samples(monkeypatch)
    _stub_synthesis_sequence(monkeypatch, [
        _memo("ACN", Verdict.HOLD, tag="a", reasoning="Margin could reach 91.4%."),
        _memo("ACN", Verdict.HOLD, tag="b"),
        _memo("ACN", Verdict.HOLD, tag="c"),
    ])

    with pytest.raises(MemoVerificationError, match="91.4"):
        await nodes.synthesizer_node(_state())


# ---------------------------------------------------------------------------
# Confidence clamped by the run's own verdict samples (added 2026-08-29)
#
# `compute_confidence` reads within-trial observables and is computed before
# any vote exists, so it could report high confidence on a split verdict.
# Measured live: MSFT 0.97 on a 2-1 split against 0.94 on its unanimous
# baseline, and AVGO 0.89 on samples that did not agree at all.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_split_verdict_cannot_report_more_confidence_than_its_agreement(monkeypatch):
    """2 of 3 samples reached hold, so the memo may claim at most 2/3.

    Floored rather than rounded: `round(2/3, 2)` is 0.67, which is above the
    bound AND on the HIGH side of `_confidence_band`'s 2/3 boundary."""
    _stub_extra_panel_samples(monkeypatch)
    _stub_synthesis_sequence(monkeypatch, [
        _memo("ACN", Verdict.HOLD, tag="a", confidence=0.97),
        _memo("ACN", Verdict.SELL, tag="b", confidence=0.97),
        _memo("ACN", Verdict.HOLD, tag="c", confidence=0.97),
    ])

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.verdict == Verdict.HOLD
    assert memo.confidence == 0.66
    assert any("confidence clamped 0.97 → 0.66" in g for g in memo.data_gaps)


@pytest.mark.anyio
async def test_a_unanimous_verdict_is_left_alone(monkeypatch):
    """3 of 3 agreed, so the ceiling is 1.0 and cannot bind. The common case
    must be untouched — the clamp exists to catch self-contradiction, not to
    reprice every memo in the record."""
    _stub_extra_panel_samples(monkeypatch)
    _stub_synthesis_sequence(monkeypatch, [
        _memo("ACN", Verdict.SELL, tag="a", confidence=0.94),
        _memo("ACN", Verdict.SELL, tag="b", confidence=0.94),
        _memo("ACN", Verdict.SELL, tag="c", confidence=0.94),
    ])

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.confidence == 0.94
    assert not any("confidence clamped" in g for g in memo.data_gaps)


@pytest.mark.anyio
async def test_an_unresolved_verdict_is_clamped_to_its_best_agreement(monkeypatch):
    """buy/sell/hold: no verdict got more than 1 of 3. AVGO's Phase 9 run
    reported 0.89 in exactly this shape."""
    _stub_extra_panel_samples(monkeypatch)
    _stub_synthesis_sequence(monkeypatch, [
        _memo("ACN", Verdict.BUY, tag="a", confidence=0.89),
        _memo("ACN", Verdict.SELL, tag="b", confidence=0.89),
        _memo("ACN", Verdict.HOLD, tag="c", confidence=0.89),
    ])

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.verdict == Verdict.UNRESOLVED
    assert memo.confidence == 0.33


@pytest.mark.anyio
async def test_confidence_below_the_ceiling_is_not_raised_to_meet_it(monkeypatch):
    """The bound is a ceiling, not a target. A 2-1 split whose confidence is
    already 0.20 stays at 0.20 — clamping is one-directional."""
    _stub_extra_panel_samples(monkeypatch)
    _stub_synthesis_sequence(monkeypatch, [
        _memo("ACN", Verdict.HOLD, tag="a", confidence=0.20),
        _memo("ACN", Verdict.SELL, tag="b", confidence=0.20),
        _memo("ACN", Verdict.HOLD, tag="c", confidence=0.20),
    ])

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.confidence == 0.20
    assert not any("confidence clamped" in g for g in memo.data_gaps)


@pytest.mark.anyio
async def test_a_memo_with_no_sampling_is_not_clamped_against_a_vote_that_never_happened(
    monkeypatch,
):
    """`--only technical`: no risk panel, so `verdict_samples` is empty and
    the single Judge call's confidence passes through untouched."""

    async def fake_run_synthesis(state, *, ledger, base_gaps, base_evidence, as_of, client=None):
        return _memo("ACN", Verdict.HOLD, tag="only", confidence=0.91)

    monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)

    memo = (await nodes.synthesizer_node(_state(risk_turns=[])))["decision_memo"]

    assert memo.verdict_samples == []
    assert memo.confidence == 0.91


@pytest.mark.anyio
async def test_a_dropped_trial_lowers_the_ceiling_it_is_measured_against(monkeypatch):
    """One trial dropped by the fabrication guard leaves 2 surviving samples.
    The ceiling is k/n over what SURVIVED (2/2 = 1.0, no clamp) — the weaker
    evidence behind a 2-sample vote is reported by the existing dropped-sample
    caveat, not by silently deflating the number."""
    _stub_extra_panel_samples(monkeypatch)
    memos = iter([
        _memo("ACN", Verdict.HOLD, tag="a", confidence=0.90),
        SynthesisFabricationError("fabricated: 12.3"),
        _memo("ACN", Verdict.HOLD, tag="c", confidence=0.90),
    ])

    async def fake_run_synthesis(state, *, ledger, base_gaps, base_evidence, as_of, client=None):
        item = next(memos)
        if isinstance(item, Exception):
            item.cost_events = []
            raise item
        return item

    monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)

    memo = (await nodes.synthesizer_node(_state()))["decision_memo"]

    assert memo.verdict_samples == ["hold", "hold"]
    assert memo.confidence == 0.90
    assert any("dropped by the citation/fabrication guard" in g for g in memo.data_gaps)
