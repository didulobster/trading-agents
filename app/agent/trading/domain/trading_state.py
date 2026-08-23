import operator
from datetime import date
from typing import Annotated, TypedDict
from app.agent.trading.domain.debate import DebateTurn
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

    # The debate transcript, one entry per turn. An add-reducer, because the
    # debate is a CYCLE: bull_turn and bear_turn each run several times and a
    # plain overwrite channel would keep only the last turn. Nodes return a
    # one-element delta (`{"debate_turns": [turn]}`), never the accumulated
    # list — returning the whole list doubles it every super-step, and that
    # failure looks exactly like the runaway loop the round cap exists to
    # prevent.
    #
    # There is deliberately no separate round counter: round state IS
    # len(debate_turns). A counter beside the list is a second source of
    # truth that can desync, and a desync shows up as either an early stop or
    # a runaway — both silent.
    debate_turns: Annotated[list[DebateTurn], operator.add]

    # Which termination layer stopped the debate: "round_cap" | "unproductive"
    # | "no_evidence" | "". Recorded because a capped debate reads in the memo
    # exactly like a resolved one unless the memo says otherwise.
    debate_terminated_by: str
    risk_summary: str
    decision_memo: DecisionMemo