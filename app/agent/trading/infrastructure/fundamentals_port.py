"""Wraps researcher.py's existing agent for the trading pipeline.
Deliberately calls the same path as `python -m app.agent.researcher TICKER`
(full checklist mode) — not /ask, which is a different agent behavior.
"""
from datetime import date

from app.agent.researcher import run_agent
from app.agent.prompts import ANALYST_SYSTEM_PROMPT 
from app.agent.trading.domain.fundamentals_report import FundamentalsReport


async def get_fundamentals_report(ticker: str) -> FundamentalsReport:
    today = date.today()
    task = f"Today's date is {today.isoformat()}. Run the full research checklist for {ticker}."
    result, usage = await run_agent(task, ANALYST_SYSTEM_PROMPT)

    return FundamentalsReport(
        ticker=ticker,
        summary=result,
        input_tokens=usage.input_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        output_tokens=usage.output_tokens,
        generated_at=today,
    )