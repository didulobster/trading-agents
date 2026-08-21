from datetime import date
from typing import TypedDict
from app.agent.trading.domain.decision_memo import DecisionMemo
from app.agent.trading.domain.fundamentals_report import FundamentalsReport
from app.agent.trading.domain.technical_report import TechnicalReport


class TradingState(TypedDict, total=False):
    ticker: str
    # Analysis date — the upper bound for ALL point-in-time data. Set once at
    # graph entry (CLI --as-of), never computed inside a node: a node calling
    # date.today() internally makes probe-date runs impossible to verify.
    as_of_date: date
    fundamentals_report: FundamentalsReport
    technical_report: TechnicalReport
    news_report: str
    sentiment_report: str
    debate_summary: str
    risk_summary: str
    decision_memo: DecisionMemo