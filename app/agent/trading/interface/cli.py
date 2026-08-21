import argparse
import asyncio
import json
from datetime import date

from app.agent.trading.infrastructure.checkpointer import build_checkpointer
from app.agent.trading.infrastructure.graph import build_trading_graph


async def run(ticker: str, thread_id: str | None, as_of: date) -> None:
    thread_id = thread_id or f"trading-{ticker}"
    async with build_checkpointer() as checkpointer:
        graph = build_trading_graph(checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        state = await graph.aget_state(config)

        if state.values and not state.next:
            print(f"Run already completed for {ticker} (thread {thread_id})")
            result = state.values
        elif state.next:
            print(f"Resuming unfinished run for {ticker} at: {state.next}")
            result = await graph.ainvoke(None, config=config)
        else:
            print(f"Starting new run for {ticker}")
            result = await graph.ainvoke(
                {"ticker": ticker, "as_of_date": as_of}, config=config
            )

    fundamentals = result.get("fundamentals_report")
    if fundamentals is not None:
        print("\n--- Fundamentals Report ---")
        print(fundamentals.summary)
        print(f"(tokens: in={fundamentals.input_tokens} out={fundamentals.output_tokens})")
        print("--- end Fundamentals Report ---\n")

    technical = result.get("technical_report")
    if technical is not None:
        print("\n--- Technical Report ---")
        print(f"source={technical.data_source} bars={technical.bars_used} as_of={technical.as_of_date}")
        print(technical.indicators.model_dump_json(indent=2))
        print(f"\n{technical.interpretation}")
        if technical.interpretation_flagged_numbers:
            print(f"[flagged numbers] {technical.interpretation_flagged_numbers}")
        print("--- end Technical Report ---\n")

    digest = result.get("news_digest")
    if digest is not None:
        print("\n--- News Digest ---")
        print(
            f"window={digest.window_start}..{digest.as_of_date} "
            f"items={len(digest.items)} raw={digest.raw_article_count} "
            f"truncated_by_cap={digest.truncated_by_cap}"
        )
        for item in digest.items:
            print(
                f"[{item.published_date}] {item.relevance:9} ({item.sentiment}) "
                f"{item.headline}"
            )
            print(f"    {item.summary}")
        issues = result.get("news_digest_issues") or []
        if issues:
            print(f"[digest issues] {issues}")
        print("--- end News Digest ---\n")

    sentiment = result.get("sentiment_summary")
    if sentiment is not None:
        print("\n--- Sentiment Summary ---")
        print(
            f"+{sentiment.positive} / -{sentiment.negative} / ={sentiment.neutral} "
            f"over {sentiment.article_count} articles  "
            f"net_score={sentiment.net_score:+.2f}"
        )
        if sentiment.excluded_by_relevance:
            print(
                f"({sentiment.excluded_by_relevance} of "
                f"{sentiment.article_count + sentiment.excluded_by_relevance} "
                f"digest articles excluded as not primarily about "
                f"{sentiment.ticker})"
            )
        if sentiment.article_count == 0:
            print("(no articles primarily about this company — net_score is "
                  "an absence of evidence, not neutral evidence)")
        print("--- end Sentiment Summary ---\n")

    memo = result["decision_memo"]
    print(json.dumps(memo.model_dump(mode="json"), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the trading pipeline for a single ticker")
    parser.add_argument("ticker")
    parser.add_argument("--thread-id", default=None)
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=date.today(),  # today() appears exactly once, at the boundary
        help="Analysis date. All news is bounded at or before this date.",
    )
    args = parser.parse_args()
    asyncio.run(run(args.ticker, args.thread_id, args.as_of))


if __name__ == "__main__":
    main()