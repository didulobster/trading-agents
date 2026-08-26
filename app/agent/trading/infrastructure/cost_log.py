"""Turns an already-logged LLM call into the `CostEvent` that rides in
`TradingState.cost_events`, and writes the run-level summary line.

Deliberately NOT a wrapper around `researcher.log_cost` — every port module
already calls `log_cost(...)` directly, and several tests monkeypatch that
exact call (`monkeypatch.setattr(port, "log_cost", ...)`) to keep from
writing to the real `docs/cost-log.jsonl` during a run that never touches
the network. A wrapper that called `log_cost` from a second module would
bypass those patches — the module a name is imported into, not the module it
was defined in, is what monkeypatch replaces. So `record_cost_event` takes
the cost `log_cost` already computed as a plain argument instead of
recomputing or re-logging it: one number, two representations (the disk line
and the state event), never two sources of truth for it.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path

from app.agent.researcher import UsageSummary
from app.agent.trading.domain.budget import CostEvent, RunBudget, RunTermination, total_spend

_COST_LOG_PATH = Path("docs/cost-log.jsonl")

# The growing-transcript stages criterion 3's cache-read ratio is about —
# NOT the analyst or synthesis nodes, whose evidence pack is sent once, not
# re-sent turn over turn.
_DEBATE_STAGE_NODES = frozenset(
    {"bull_turn", "bear_turn", "neutral_turn", "aggressive_turn", "conservative_turn"}
)


def new_event_id(node: str, *, turn_index: int | None = None) -> str:
    """Generated BEFORE the sibling `log_cost(...)` call at each site, and
    passed to both it and `record_cost_event` below — so the disk line and
    the state event carry the identical id. (First measured live run showed
    why this has to be a separate, earlier step: generating the id inside
    `record_cost_event`, called AFTER `log_cost`, left every disk line's
    `event_id` null — the two were never the same string.)"""
    suffix = f":{turn_index}" if turn_index is not None else ""
    return f"{node}{suffix}:{uuid.uuid4().hex[:8]}"


def record_cost_event(
    event_id: str,
    node: str,
    usage: UsageSummary,
    model: str,
    cost: float | None,
) -> CostEvent:
    """`cost` is whatever the sibling `log_cost(...)` call at the same call
    site already returned — never recomputed here, so the state event and
    the disk line can never disagree about the dollar amount. `event_id`
    comes from `new_event_id()`, called once per site and passed to both."""
    return CostEvent(
        event_id=event_id,
        node=node,
        model=model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_creation_input_tokens=usage.cache_write_tokens,
        cache_read_input_tokens=usage.cache_read_tokens,
        usd=cost if cost is not None else 0.0,
    )


def _cache_read_ratio(events: list[CostEvent]) -> float | None:
    debate_stage = [e for e in events if e.node in _DEBATE_STAGE_NODES]
    if not debate_stage:
        return None
    read = sum(e.cache_read_input_tokens for e in debate_stage)
    denom = read + sum(
        e.input_tokens + e.cache_creation_input_tokens for e in debate_stage
    )
    return round(read / denom, 4) if denom else None


def log_run_summary(
    *,
    run_id: str,
    ticker: str,
    as_of_date: date,
    events: list[CostEvent],
    budget: RunBudget,
    terminated_by: RunTermination,
    wall_clock_s: float,
) -> None:
    """Written exactly once per run — completed or aborted — right after the
    vault artifacts save in cli.py. That one-line-per-run invariant is what
    makes criterion 1 ("every run_summary shows total_usd <= 0.60") a single
    `jq` query rather than a reconstruction from per-call lines."""
    entry = {
        "kind": "run_summary",
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "ticker": ticker,
        "as_of_date": as_of_date.isoformat(),
        "total_usd": round(total_spend(events), 6),
        "budget_max_usd": budget.max_usd,
        "terminated_by": terminated_by.value,
        "cache_read_ratio": _cache_read_ratio(events),
        "n_events": len(events),
        "wall_clock_s": round(wall_clock_s, 3),
    }
    _COST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _COST_LOG_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")
