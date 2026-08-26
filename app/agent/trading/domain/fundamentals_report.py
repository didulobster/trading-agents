from datetime import date
from pydantic import BaseModel

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