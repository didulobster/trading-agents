from datetime import date
from pydantic import BaseModel, Field, model_validator

from app.agent.trading.domain.budget import CostEvent


class FundamentalsReport(BaseModel):
    ticker: str
    summary: str
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    generated_at: date
    # None on a cache hit (get_fundamentals_report returned a cached report
    # without calling the LLM) — a cached run spent nothing this run, and
    # cost_events must reflect that, not the cost of whichever run first
    # produced the cache.
    cost_event: CostEvent | None = None
    # The research agent's TOOLS spend money too: `ask_edgar` and
    # `extract_metrics` are HTTP calls to the FastAPI app that run their own
    # LLM calls server-side. Kept apart from `cost_event` so the agent's own
    # loop stays separately measurable -- `cache_read_ratio` and the
    # turn-count analysis both read the loop's numbers, and mixing ~110k
    # un-cached tool tokens into them would make every caching metric
    # meaningless. One event per server-side model, since each is priced at
    # its own rate. Empty when nothing was delegated.
    tool_cost_events: list[CostEvent] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_single_tool_cost_event(cls, data):
        """Reports cached or checkpointed before 2026-09-11 carry one
        `tool_cost_event`. Dropped silently, that spend would vanish from a
        resumed run's ledger, so it is carried into the list instead."""
        if isinstance(data, dict) and "tool_cost_event" in data:
            data = dict(data)
            legacy = data.pop("tool_cost_event")
            if legacy is not None and not data.get("tool_cost_events"):
                data["tool_cost_events"] = [legacy]
        return data
