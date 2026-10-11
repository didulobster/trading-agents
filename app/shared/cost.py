"""Token usage, its price, and the monthly cost log every LLM call appends to."""

import json
from datetime import datetime

from app.shared.cost_log_path import cost_log_path
from app.shared.llm import MODEL_PRICING


class UsageSummary:
    __slots__ = ("input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens")

    def __init__(self) -> None:
        self.input_tokens = 0
        self.cache_write_tokens = 0
        self.cache_read_tokens = 0
        self.output_tokens = 0


def compute_cost(usage: UsageSummary, model: str) -> float | None:
    """Estimate USD cost from token usage, or None if `model` isn't priced.

    `model` is required: it used to default to the research agent's model,
    and two trading ports priced their calls at that rate by omission."""
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return None
    return round(
        usage.input_tokens * pricing["input"] / 1_000_000
        + usage.cache_write_tokens * pricing["cache_write"] / 1_000_000
        + usage.cache_read_tokens * pricing["cache_read"] / 1_000_000
        + usage.output_tokens * pricing["output"] / 1_000_000,
        6,
    )


def log_cost(
    ticker: str,
    mode: str,
    usage: UsageSummary,
    model: str,
    *,
    run_id: str | None = None,
    event_id: str | None = None,
) -> float | None:
    """Append one JSON line to this month's cost log. Returns the estimated
    cost (or None if pricing isn't configured), so callers can also surface
    it elsewhere (e.g. in the memo itself).

    Both the logged label and the price come from `model` — a hardcoded label
    on a differently-priced call produces a log that is wrong twice and looks
    right.

    `run_id`/`event_id` (Phase 8) are None for calls outside the trading
    graph — the standalone researcher CLI has no run to group lines under.
    Trading-pipeline callers pass both (see
    trading/infrastructure/cost_log.py) so a run's lines can be grouped and
    a resumed run's duplicate write can be deduped, both by `jq` over this
    file alone. `kind` distinguishes these lines from the pre-Phase-8 lines
    already in this file, which have neither field and are read as legacy."""
    cost = compute_cost(usage, model)
    entry = {
        "kind": "cost_event",
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "event_id": event_id,
        "ticker": ticker,
        "mode": mode,
        "model": model,
        "input_tokens": usage.input_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "output_tokens": usage.output_tokens,
        "estimated_cost_usd": cost,
    }
    # Resolved from the repo, not the working directory: this was
    # Path("docs/cost-log.jsonl"), so a run started elsewhere wrote a log
    # that log_run_summary's disk reconciliation never read.
    log_path = cost_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    return cost
