"""Trading's HTTP endpoint: one pipeline run per request. Mounted by app/main.py."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.shared.api_key import SPENDS_MONEY
from app.shared.ticker import Ticker
from app.shared.vault import vault_run
from app.agent.trading.domain.decision_memo import DecisionMemo
from app.agent.trading.interface.runner import (
    DEFAULT_MAX_USD,
    DEFAULT_WALL_CLOCK_TIMEOUT_S,
    default_thread_id,
    save_vault_artifacts,
    start_or_resume,
)

router = APIRouter()


class TradingAnalysisRequest(BaseModel):
    # Unknown fields are rejected, not dropped: see AskRequest in
    # app/edgar_research/api.py.
    model_config = ConfigDict(extra="forbid")

    ticker: Ticker
    thread_id: str | None = None
    # Same defaults as the CLI. `as_of_date` falls back to today HERE, at the
    # boundary — never inside a node (see TradingState.as_of_date). All three
    # apply only to a NEW run: a resume inherits its checkpoint's values.
    as_of_date: date | None = None
    max_usd: float = Field(DEFAULT_MAX_USD, gt=0)
    wall_clock_timeout_s: float = Field(DEFAULT_WALL_CLOCK_TIMEOUT_S, gt=0)

class TradingAnalysisResponse(BaseModel):
    ticker: str
    thread_id: str
    status: Literal["completed", "resumed", "started"]
    # None when the run-level budget or deadline guard stopped the run before
    # synthesis; `run_terminated_by` then says which one.
    decision_memo: DecisionMemo | None = None
    run_terminated_by: str | None = None


@router.post("/trading/analyze", response_model=TradingAnalysisResponse, dependencies=SPENDS_MONEY)
async def trading_analyze(req: TradingAnalysisRequest, request: Request) -> TradingAnalysisResponse:
    """Run the trading pipeline for one ticker, exactly as the CLI does.

    Blocks for the whole run (minutes). The run lifecycle — initial state,
    budget, recursion limit, stale-resume refusal, run summary, vault
    artifacts — is `interface.runner`'s, shared with the CLI, so the two
    entry points cannot drift apart again.
    """
    if not req.ticker.strip():
        raise HTTPException(400, "ticker must not be empty")

    ticker = req.ticker.strip().upper()
    thread_id = req.thread_id or default_thread_id(ticker)
    as_of = req.as_of_date or date.today()
    graph = request.app.state.trading_graph

    with vault_run():
        outcome = await start_or_resume(
            graph, ticker, thread_id, as_of,
            max_usd=req.max_usd, wall_clock_timeout_s=req.wall_clock_timeout_s,
        )
        if outcome.status == "refused":
            raise HTTPException(409, outcome.refusal)
        # No terminal capture in a server process — it would interleave every
        # concurrent request's output — so the artifacts carry no run log.
        save_vault_artifacts(outcome.result, run_log="")

    result = outcome.result
    terminated_by = result.get("run_terminated_by")
    return TradingAnalysisResponse(
        ticker=ticker,
        thread_id=thread_id,
        status=outcome.status,
        decision_memo=result.get("decision_memo"),
        run_terminated_by=terminated_by.value if terminated_by else None,
    )
