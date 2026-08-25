"""Phase 6 exit-criteria verification (the criteria as actually specified,
not the engineering-quality bar the rest of Phase 6 was originally built
against):

  1. DETERMINISM — replay the SAME debate transcript through the risk panel
     + Research Manager + Risk Judge TWICE at temperature=0. The Risk
     Judge's verdict (buy/sell/hold) must be identical both times.
  2. STABILITY — run the same pipeline 3 times at PRODUCTION temperature
     (i.e. the real default: no explicit temperature, adaptive thinking on,
     exactly what every live run in this project actually uses) over the
     same fixed debate transcript. All three verdicts must agree on
     DIRECTION, even though wording will differ.

"Same debate transcript" means the debate itself is generated ONCE (real
API calls, not a hand-built fixture) and then held fixed across every
trial — only the risk panel, Research Manager, and Risk Judge are re-run
per trial. At temperature=0 that means EVERY risk-panel turn runs at 0, not
just the Risk Judge: the criterion is about the reproducibility of the
whole downstream process given fixed upstream input, and a Risk Judge that
is itself deterministic over a risk ledger that varies run to run would not
actually demonstrate that.

Cost: one real debate (6 turns) generated once and reused as fixed input;
5 trials of the risk panel (9 turns each, RISK_MAX_ROUNDS=3) + Research
Manager + Risk Judge (2 trials at temperature=0, 3 at production
temperature). Risk panel model follows TRADING_RISK_MODEL/LLM_CLAUDE_MODEL
as normal; Research Manager and Risk Judge are pinned to Sonnet per the
spec, via synthesis_port.RESEARCH_MANAGER_MODEL/RISK_JUDGE_MODEL.

Run:

    uv run python -m scripts.risk_determinism_check TICKER [--as-of YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from anthropic import AsyncAnthropic

from app.agent.trading.application import nodes
from app.agent.trading.application.debate_router import MAX_TURNS as DEBATE_MAX_TURNS
from app.agent.trading.application.risk_ledger import build_risk_ledger
from app.agent.trading.application.risk_router import RISK_MAX_TURNS
from app.agent.trading.application.technical_indicators import compute_indicators
from app.agent.trading.domain.risk import PERSONAS
from app.agent.trading.domain.technical_report import TechnicalReport
from app.agent.trading.infrastructure.debate_port import run_debate_turn
from app.agent.trading.infrastructure.price_data_port import get_price_history
from app.agent.trading.infrastructure.risk_port import run_risk_turn
from app.agent.trading.infrastructure.synthesis_port import run_synthesis
from app.agent.trading.infrastructure.technical_interpreter_port import interpret_indicators


async def build_fixed_debate_state(ticker: str, as_of: date, client: AsyncAnthropic) -> dict:
    """Real technical report + a real 6-turn debate, generated ONCE. This
    becomes the fixed input every trial below replays against — technical-
    only, same reason every other Phase 6 live check in this project used
    `--only technical`: it needs no local RAG API server and no EDGAR
    corpus, so the cost and moving parts are scoped to what's under test.
    """
    df, source, dropped = await get_price_history(ticker, as_of)
    indicators = compute_indicators(df)
    interpretation, flagged, flagged_claims, _ = await interpret_indicators(ticker, indicators)
    technical_report = TechnicalReport(
        ticker=ticker, as_of_date=df.index[-1].date(), data_source=source,
        bars_used=len(df), bars_dropped_invalid=dropped, indicators=indicators,
        interpretation=interpretation, interpretation_flagged_numbers=flagged,
        interpretation_flagged_claims=flagged_claims,
    )
    state: dict = {"ticker": ticker, "as_of_date": as_of, "technical_report": technical_report}

    turns = []
    for i in range(DEBATE_MAX_TURNS):
        side = "bull" if i % 2 == 0 else "bear"
        turn = await run_debate_turn(state={**state, "debate_turns": turns}, side=side,
                                      turn_index=i, client=client)
        turns.append(turn)
    state["debate_turns"] = turns
    print(f"[fixed input] debate: {len(turns)} turns, "
          f"terminated by round_cap (fixed for every trial below)")
    return state


async def run_pipeline_once(
    fixed_state: dict, *, temperature: float | None, client: AsyncAnthropic, label: str,
) -> tuple[str, dict]:
    """Fresh risk panel (from an empty risk_turns) + Research Manager + Risk
    Judge, over the SAME fixed debate. Returns (verdict, detail dict)."""
    trial_state = dict(fixed_state)
    turns = []
    for i in range(RISK_MAX_TURNS):
        persona = PERSONAS[i % len(PERSONAS)]
        turn = await run_risk_turn(
            {**trial_state, "risk_turns": turns}, persona, i,
            client=client, temperature=temperature,
        )
        turns.append(turn)
    trial_state["risk_turns"] = turns
    trial_state["risk_terminated_by"] = "round_cap"
    trial_state["debate_terminated_by"] = "round_cap"

    ledger = build_risk_ledger(turns)
    debate_gaps, debate_evidence = nodes._debate_caveats(trial_state)
    risk_gaps, risk_evidence, _ = nodes._risk_caveats(trial_state)

    memo = await run_synthesis(
        trial_state, ledger=ledger,
        base_gaps=debate_gaps + risk_gaps, base_evidence=debate_evidence + risk_evidence,
        as_of=trial_state["as_of_date"], client=client,
        research_temperature=temperature, risk_temperature=temperature,
    )
    contested = sum(1 for e in ledger if e.contested)
    detail = {
        "label": label, "temperature": temperature, "verdict": memo.verdict.value,
        "research_preliminary_verdict": memo.research_preliminary_verdict.value,
        "overridden": memo.verdict != memo.research_preliminary_verdict,
        "ledger_size": len(ledger), "contested": contested, "confidence": memo.confidence,
    }
    print(f"[{label}] temperature={temperature} verdict={memo.verdict.value} "
          f"(research lean: {memo.research_preliminary_verdict.value}"
          f"{', OVERRIDDEN' if detail['overridden'] else ''}) "
          f"ledger={len(ledger)} contested={contested} confidence={memo.confidence}")
    return memo.verdict.value, detail


async def main(ticker: str, as_of: date) -> None:
    client = AsyncAnthropic()
    fixed_state = await build_fixed_debate_state(ticker, as_of, client)

    print("\n=== 1. DETERMINISM: same debate, temperature=0, twice ===")
    det_results = []
    for i in range(2):
        verdict, detail = await run_pipeline_once(
            fixed_state, temperature=0.0, client=client, label=f"determinism-{i + 1}"
        )
        det_results.append(detail)
    determinism_holds = det_results[0]["verdict"] == det_results[1]["verdict"]
    print(f"\nDETERMINISM: {'PASS' if determinism_holds else 'FAIL'} — "
          f"{det_results[0]['verdict']} vs {det_results[1]['verdict']}")

    print("\n=== 2. STABILITY: same debate, production temperature, 3 samples ===")
    stab_results = []
    for i in range(3):
        verdict, detail = await run_pipeline_once(
            fixed_state, temperature=None, client=client, label=f"stability-{i + 1}"
        )
        stab_results.append(detail)
    directions = {r["verdict"] for r in stab_results}
    stability_holds = len(directions) == 1
    print(f"\nSTABILITY: {'PASS' if stability_holds else 'FAIL'} — "
          f"verdicts: {[r['verdict'] for r in stab_results]}")

    print("\n=== Summary ===")
    print(json.dumps({"determinism": det_results, "stability": stab_results}, indent=2))
    print(f"\nDeterminism (temp=0, replayed twice): {'PASS' if determinism_holds else 'FAIL'}")
    print(f"Stability (production temp, 3 samples): {'PASS' if stability_holds else 'FAIL'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    asyncio.run(main(args.ticker, args.as_of))
