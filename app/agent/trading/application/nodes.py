"""Phase 1 stub nodes — placeholder logic only.
Each returns a hardcoded value; real logic lands in Phases 2-6.
Goal here is proving the topology runs end-to-end and emits a
schema-valid DecisionMemo, nothing more.
"""
import asyncio
from datetime import date

from app.agent.trading.domain.decision_memo import DecisionMemo, Verdict
from app.agent.trading.domain.technical_report import TechnicalReport
from app.agent.trading.domain.trading_state import TradingState
from app.agent.trading.infrastructure.fundamentals_port import get_fundamentals_report
from app.agent.trading.infrastructure.price_data_port import get_price_history
from app.agent.trading.application.technical_indicators import compute_indicators
from app.agent.trading.infrastructure.technical_interpreter_port import interpret_indicators, save_technical_report


async def fundamentals_node(state: TradingState) -> dict:
    print(f"[fundamentals] running for {state['ticker']}")
    report = await get_fundamentals_report(state["ticker"])
    return {"fundamentals_report": report}


async def technical_node(state: TradingState) -> dict:
    ticker = state["ticker"]
    print(f"[technical] running for {ticker}")

    df, source = await get_price_history(ticker)
    indicators = compute_indicators(df)
    interpretation, flagged, cost_usd = await interpret_indicators(ticker, indicators)

    report = TechnicalReport(
        ticker=ticker,
        as_of_date=df.index[-1].date(),
        data_source=source,
        bars_used=len(df),
        indicators=indicators,
        interpretation=interpretation,
        interpretation_flagged_numbers=flagged,
    )
    vault_path = save_technical_report(report, cost_usd=cost_usd)
    print(f"[technical] saved report to {vault_path}")
    return {"technical_report": report}


async def news_node(state: TradingState) -> dict:
    print(f"[news] STUB running for {state['ticker']}")
    return {"news_report": "STUB — Phase 4 wires this to Finnhub"}


async def sentiment_node(state: TradingState) -> dict:
    print(f"[sentiment] STUB running for {state['ticker']}")
    return {"sentiment_report": "STUB — Phase 4"}


async def debate_node(state: TradingState) -> dict:
    print(f"[debate] STUB running for {state['ticker']}")
    return {"debate_summary": "STUB — Phase 5"}


async def risk_node(state: TradingState) -> dict:
    print(f"[risk] STUB running for {state['ticker']}")
    return {"risk_summary": "STUB — Phase 6"}


async def synthesizer_node(state: TradingState) -> dict:
    print(f"[synthesizer] STUB running for {state['ticker']}")
    memo = DecisionMemo(
        ticker=state["ticker"],
        bull_case="STUB",
        bear_case="STUB",
        risk_debate_summary=state["risk_summary"],
        technical_signal=state["technical_report"].interpretation,
        reasoning="STUB — synthesis logic not yet implemented. fundamentals_report is real (Phase 2); technical/news/sentiment/debate/risk are still stubs.",
        suggested_strategy="STUB",
        verdict=Verdict.HOLD,
        confidence=0.0,
        data_as_of_date=date.today(),
        data_gaps=[
            "synthesizer does not yet incorporate fundamentals_report into this memo — that's a later phase, not Phase 2's scope",
            "technical/news/sentiment/debate/risk nodes are still stubs — no real data",
        ],
        assumptions=[],
        evidence=[],
    )
    return {"decision_memo": memo}