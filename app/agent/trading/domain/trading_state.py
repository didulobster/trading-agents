from datetime import date
from typing import TypedDict
from app.agent.trading.domain.decision_memo import DecisionMemo
from app.agent.trading.domain.fundamentals_report import FundamentalsReport
from app.agent.trading.domain.news_digest import NewsDigest, SentimentSummary
from app.agent.trading.domain.technical_report import TechnicalReport


class TradingState(TypedDict, total=False):
    ticker: str
    # Analysis date — the upper bound for ALL point-in-time data. Set once at
    # graph entry (CLI --as-of), never computed inside a node: a node calling
    # date.today() internally makes probe-date runs impossible to verify.
    as_of_date: date
    fundamentals_report: FundamentalsReport
    technical_report: TechnicalReport
    news_digest: NewsDigest
    # Structural problems the digest join flagged (missing/duplicate index,
    # invalid enum) — surfaced for review, never silently absorbed.
    news_digest_issues: list[str]
    sentiment_summary: SentimentSummary
    debate_summary: str
    risk_summary: str
    decision_memo: DecisionMemo