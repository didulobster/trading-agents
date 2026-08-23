"""Phase 1 stub nodes — placeholder logic only.
Each returns a hardcoded value; real logic lands in Phases 2-6.
Goal here is proving the topology runs end-to-end and emits a
schema-valid DecisionMemo, nothing more.
"""
import asyncio
from collections import Counter
from datetime import date

from app.agent.trading.domain.decision_memo import DecisionMemo, Verdict
from app.agent.trading.domain.news_digest import (
    AGGREGATED_RELEVANCE,
    NewsDigest,
    NewsItem,
    SentimentSummary,
)
from app.agent.trading.domain.technical_report import TechnicalReport
from app.agent.trading.domain.trading_state import TradingState
from app.agent.trading.infrastructure.fundamentals_port import get_fundamentals_report
from app.agent.trading.infrastructure.news_data_port import fetch_company_news, filter_and_dedup
from app.agent.trading.infrastructure.news_digest_port import build_digest
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

    df, source, dropped_bars = await get_price_history(ticker)
    if dropped_bars:
        print(f"[technical] dropped {dropped_bars} incomplete bar(s) from {source}")
    indicators = compute_indicators(df)
    interpretation, flagged, flagged_claims, cost_usd = await interpret_indicators(
        ticker, indicators
    )
    if flagged_claims:
        print(f"[technical] {len(flagged_claims)} contradicted claim(s): {flagged_claims}")

    report = TechnicalReport(
        ticker=ticker,
        as_of_date=df.index[-1].date(),
        data_source=source,
        bars_used=len(df),
        bars_dropped_invalid=dropped_bars,
        indicators=indicators,
        interpretation=interpretation,
        interpretation_flagged_numbers=flagged,
        interpretation_flagged_claims=flagged_claims,
    )
    vault_path = save_technical_report(report, cost_usd=cost_usd)
    print(f"[technical] saved report to {vault_path}")
    return {"technical_report": report}


async def news_node(state: TradingState) -> dict:
    ticker = state["ticker"]
    as_of = state.get("as_of_date")
    if as_of is None:
        # Fail loud rather than defaulting to today: a silent
        # `or date.today()` fallback is precisely how lookahead
        # contamination gets into a backtest.
        raise ValueError(
            "as_of_date missing from TradingState — refusing to run unbounded. "
            "A news fetch without an explicit upper bound is a lookahead bug."
        )
    print(f"[news] running for {ticker} as of {as_of}")

    raw, window_start = await fetch_company_news(ticker, as_of)
    clean, dropped_win, dropped_missing, truncated = filter_and_dedup(
        raw, as_of, window_start
    )

    items, issues, cost_usd = await build_digest(clean, ticker)

    digest = NewsDigest(
        ticker=ticker,
        as_of_date=as_of,
        window_start=window_start,
        items=items,
        raw_article_count=len(raw),
        deduped_count=len(clean),
        dropped_out_of_window=dropped_win,
        dropped_missing_date=dropped_missing,
        truncated_by_cap=truncated,
    )

    # Belt-and-braces post-assertion. Cheap, and it turns a silent
    # correctness bug into a loud one at exactly the right moment.
    late = [i for i in digest.items if i.published_date > as_of]
    if late:
        raise AssertionError(
            f"Lookahead leak: {len(late)} article(s) dated after {as_of} "
            f"reached the digest — first: {late[0].published_date}"
        )

    print(
        f"[news] {len(items)} items (raw={len(raw)} deduped={len(clean)} "
        f"truncated={truncated}) cost={cost_usd}"
    )
    return {"news_digest": digest, "news_digest_issues": issues}


async def sentiment_node(state: TradingState) -> dict:
    """Deterministic aggregation over NewsDigest.items — no LLM, no network.

    Only articles whose relevance is in AGGREGATED_RELEVANCE are counted.
    The vendor feed tags broad sector coverage with the requested ticker, so
    aggregating everything measures the sector rather than the company.

    Two different situations both produce net_score=0.0 with
    article_count=0 — a genuinely quiet ticker, and a noisy feed where
    nothing was actually about the company — and neither is
    neutrality-with-evidence. `excluded_by_relevance` is what tells them
    apart downstream."""
    digest: NewsDigest = state["news_digest"]

    # A checkpoint written before a NewsItem field was added deserializes with
    # the outer NewsDigest intact but its items left as plain dicts — pydantic
    # cannot rebuild a child that is missing a now-required field, and nothing
    # raises at the read. Without this the first symptom is an AttributeError
    # on the new field, several frames from the actual cause. Same reason
    # news_node refuses to run without as_of_date: name the real problem at
    # the point it becomes knowable.
    stale = [i for i in digest.items if not isinstance(i, NewsItem)]
    if stale:
        raise TypeError(
            f"news_digest.items holds {len(stale)} {type(stale[0]).__name__} "
            f"entr{'y' if len(stale) == 1 else 'ies'} instead of NewsItem — this "
            f"checkpoint predates a NewsItem schema change and cannot be resumed. "
            f"Re-run the ticker under a new --thread-id."
        )

    relevant = [i for i in digest.items if i.relevance in AGGREGATED_RELEVANCE]
    excluded = len(digest.items) - len(relevant)
    print(
        f"[sentiment] aggregating {len(relevant)} of {len(digest.items)} items "
        f"for {digest.ticker} ({excluded} excluded by relevance)"
    )
    counts = Counter(i.sentiment for i in relevant)
    pos, neg, neu = counts["positive"], counts["negative"], counts["neutral"]
    total = pos + neg + neu
    return {
        "sentiment_summary": SentimentSummary(
            ticker=digest.ticker,
            as_of_date=digest.as_of_date,
            positive=pos,
            negative=neg,
            neutral=neu,
            net_score=(pos - neg) / total if total else 0.0,
            article_count=total,
            excluded_by_relevance=excluded,
        )
    }


async def debate_node(state: TradingState) -> dict:
    print(f"[debate] STUB running for {state['ticker']}")
    return {"debate_summary": "STUB — Phase 5"}


async def risk_node(state: TradingState) -> dict:
    print(f"[risk] STUB running for {state['ticker']}")
    return {"risk_summary": "STUB — Phase 6"}


# What each analyst leg is expected to leave behind in state. A partial run is
# a legitimate mode (--only), so a missing report is recorded as a data gap
# rather than raising — but the memo must never present a gap as a finding.
ANALYST_OUTPUTS = {
    "fundamentals": "fundamentals_report",
    "technical": "technical_report",
    "news": "news_digest",
}


async def synthesizer_node(state: TradingState) -> dict:
    print(f"[synthesizer] STUB running for {state['ticker']}")
    missing = sorted(
        name for name, key in ANALYST_OUTPUTS.items() if state.get(key) is None
    )
    technical = state.get("technical_report")
    memo = DecisionMemo(
        ticker=state["ticker"],
        bull_case="STUB",
        bear_case="STUB",
        risk_debate_summary=state["risk_summary"],
        technical_signal=(
            technical.interpretation
            if technical is not None
            else "NOT RUN — technical analyst was excluded from this run"
        ),
        reasoning="STUB — synthesis logic not yet implemented. fundamentals (Phase 2), technical (Phase 3), and news/sentiment (Phase 4) are real; debate/risk are still stubs.",
        suggested_strategy="STUB",
        verdict=Verdict.HOLD,
        confidence=0.0,
        data_as_of_date=date.today(),
        data_gaps=[
            "synthesizer does not yet incorporate fundamentals_report into this memo — that's a later phase, not Phase 2's scope",
            "debate/risk nodes are still stubs — no real data",
        ]
        + [
            f"{name} analyst did not run — this memo carries no {name} evidence "
            f"at all, which is not the same as that evidence being neutral"
            for name in missing
        ],
        assumptions=[],
        evidence=[],
    )
    return {"decision_memo": memo}