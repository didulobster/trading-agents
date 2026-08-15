from typing import TypedDict
from app.agent.trading.domain.decision_memo import DecisionMemo
from app.agent.trading.domain.fundamentals_report import FundamentalsReport


class TradingState(TypedDict, total=False):
    ticker: str
    fundamentals_report: FundamentalsReport
    technical_report: str
    news_report: str
    sentiment_report: str
    debate_summary: str
    risk_summary: str
    decision_memo: DecisionMemo