"""Turns EDGAR Research's fundamentals memo into Trading's fundamentals report.

The memo comes from `write_fundamentals_memo`, the same full-checklist run as
`python -m app.edgar_research.agent.researcher TICKER` — not /ask, which is a
different agent behavior. This side owns the budget, the cost log and the
cache; EDGAR Research owns the prompt, the model and its tools' pricing.
"""
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from app.edgar_research.fundamentals_memo import Spend, write_fundamentals_memo
from app.shared.cost import log_cost
from app.shared.vault import save_output
from app.trading.application.guards import check_run_guards
from app.trading.domain.budget import CostEvent, RunBudget
from app.trading.domain.fundamentals_report import FundamentalsReport
from app.trading.infrastructure.cost_log import new_event_id, record_cost_event

_CACHE_DIR = Path(__file__).resolve().parents[1] / ".fundamentals_cache"
_USE_MOCK = os.getenv("MOCK_FUNDAMENTALS", "").strip() == "1"


def _cache_path(ticker: str, as_of: date) -> Path:
    """Keyed on the analysis date as well as the ticker.

    On ticker alone, a cached August memo answered a March run — the cache
    is written on every real run and read under MOCK_FUNDAMENTALS, so one
    environment variable was all that stood between a historical probe and
    a report from a different date.
    """
    return _CACHE_DIR / f"{ticker.upper()}-{as_of.isoformat()}.json"


def budget_stop_check(
    budget: RunBudget | None, prior_events: list[CostEvent] | None = None
) -> Callable[[Spend], str | None] | None:
    """A `write_fundamentals_memo` stop check that applies the run's budget and deadline
    INSIDE the fundamentals node.

    The graph checks `check_run_guards` only on its edges, and this node is
    one edge's worth of work: up to LOOP_MAX_TURNS model calls plus up to 30
    ask_edgar/extract_metrics calls, each with its own server-side LLM
    calls. Built on `check_run_guards` itself, over the run's earlier events
    plus one in-flight event for this loop, so a breach here means exactly
    what a breach on an edge means. None when the run has no budget (tests
    and the standalone research CLI), which keeps the loop unguarded as
    before.
    """
    if budget is None:
        return None
    prior = list(prior_events or [])

    def check(spend: Spend) -> str | None:
        spent = spend.usd
        in_flight = CostEvent(
            event_id="fundamentals:in-flight",
            node="fundamentals",
            model=spend.model,
            input_tokens=spend.usage.input_tokens,
            output_tokens=spend.usage.output_tokens,
            cache_creation_input_tokens=spend.usage.cache_write_tokens,
            cache_read_input_tokens=spend.usage.cache_read_tokens,
            usd=spent,
        )
        termination = check_run_guards([*prior, in_flight], budget, datetime.now(timezone.utc))
        if termination is None:
            return None
        return (
            f"{termination.value}: ~${spent:.4f} spent in this node against a "
            f"${budget.max_usd:.2f} run budget, deadline {budget.deadline_utc.isoformat()}"
        )

    return check


async def get_fundamentals_report(
    ticker: str,
    as_of: date,
    run_id: str | None = None,
    *,
    budget: RunBudget | None = None,
    prior_events: list[CostEvent] | None = None,
) -> FundamentalsReport:
    """The fundamentals leg, bounded at `as_of` like every other source.

    `as_of` is required, not defaulted. This node used to call
    `date.today()` and never receive the run's analysis date at all, so a
    `--as-of 2026-03-01` run bounded its prices and news at March and let
    its most heavily-weighted analyst read whatever had been filed since —
    and the memo said nothing about it. Prices and news already refuse to
    run without the date (nodes.technical_node, nodes.news_node); this now
    does too, by taking it as a positional argument nothing can omit.
    """
    cached = _cache_path(ticker, as_of)

    if _USE_MOCK and cached.exists():
        report = FundamentalsReport.model_validate_json(cached.read_text())
        print(f"[fundamentals] loading cached report for {ticker} as of {as_of}")
        return report

    memo = await write_fundamentals_memo(
        ticker, as_of, stop_check=budget_stop_check(budget, prior_events),
    )

    event_id = new_event_id("fundamentals")
    cost = log_cost(
        ticker, "trading-fundamentals", memo.usage, memo.model, run_id=run_id, event_id=event_id,
    )
    vault_path = save_output(
        memo.text, ticker.upper(), "fundamentals",
        cost_usd=cost, provenance=memo.provenance, model=memo.model,
    )
    print(f"[fundamentals] saved memo to {vault_path}")

    # What the agent's TOOLS spent server-side, which until 2026-08-27
    # reached neither the cost log nor `check_run_guards`. Logged as its own
    # line and its own CostEvent per model, under a distinct mode, so the two
    # kinds of spend stay tellable apart in `docs/cost-log.jsonl`.
    tool_events = []
    for model, tool_usage in memo.tool_usage:
        tool_event_id = new_event_id("fundamentals-tools")
        tool_cost = log_cost(
            ticker, "trading-fundamentals-tools", tool_usage, model,
            run_id=run_id, event_id=tool_event_id,
        )
        tool_events.append(record_cost_event(
            tool_event_id, "fundamentals-tools", tool_usage, model, tool_cost
        ))

    report = FundamentalsReport(
        ticker=ticker,
        summary=memo.text,
        input_tokens=memo.usage.input_tokens,
        cache_write_tokens=memo.usage.cache_write_tokens,
        cache_read_tokens=memo.usage.cache_read_tokens,
        output_tokens=memo.usage.output_tokens,
        # The analysis date, not the wall clock: a report generated today
        # about March is a March report, and dating it today is how a
        # historical probe comes to look current.
        generated_at=as_of,
        cost_event=record_cost_event(event_id, "fundamentals", memo.usage, memo.model, cost),
        tool_cost_events=tool_events,
    )

    _CACHE_DIR.mkdir(exist_ok=True)
    cached.write_text(report.model_dump_json(indent=2))

    return report
