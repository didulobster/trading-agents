import argparse
import asyncio
import json
from datetime import date

from app.agent.trading.application.debate_router import MAX_ROUNDS
from app.agent.trading.infrastructure.checkpointer import build_checkpointer
from app.agent.trading.infrastructure.debate_port import save_debate_transcript
from app.agent.trading.infrastructure.decision_memo_port import save_decision_memo
from app.agent.trading.infrastructure.graph import ALL_ANALYSTS, build_trading_graph
from app.agent.trading.infrastructure.news_digest_port import save_sentiment_report
from app.agent.trading.infrastructure.run_log import capture_terminal_log


async def run(
    ticker: str, thread_id: str | None, as_of: date, analysts: list[str] | None
) -> None:
    # A subset run has a different topology, so it gets its own default thread:
    # resuming a full run's checkpoint under a narrower graph would report the
    # cached fundamentals/technical of an earlier run as if this run produced
    # them. An explicit --thread-id still overrides, deliberately.
    suffix = "" if analysts is None else "-" + "+".join(sorted(analysts))
    thread_id = thread_id or f"trading-{ticker}{suffix}"
    if analysts is not None:
        print(f"Analysts: {', '.join(sorted(analysts))} (others skipped)")
    async with build_checkpointer() as checkpointer:
        graph = build_trading_graph(checkpointer, analysts=analysts)
        # Layer 2 of the debate's termination guarantee, behind the
        # router's own cap. DERIVED, not a literal: a hardcoded 25 silently
        # becomes a bug the day MAX_ROUNDS is raised, and it surfaces as a
        # GraphRecursionError in what looks like the risk node.
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 2 * MAX_ROUNDS + 12,   # turns + other nodes + slack
        }
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

    turns = result.get("debate_turns") or []
    if turns:
        print("\n--- Bull/Bear Debate ---")
        print(
            f"{len(turns)} turn(s) over {len(turns) // 2} round(s); "
            f"terminated by {result.get('debate_terminated_by') or 'not recorded'}"
        )
        for turn in turns:
            print(
                f"\n[turn {turn.turn_index} · round {turn.round_num}] "
                f"{turn.side.upper()} stance={turn.payload.stance}"
                + (
                    f" concedes->{turn.payload.concession_trigger}"
                    if turn.payload.concession_trigger
                    else ""
                )
                + ("" if turn.productive else " (unproductive)")
            )
            print(f"    {turn.payload.argument}")
            for claim in turn.payload.claims:
                print(f"    · {claim.claim_id} [{claim.evidence_ref}] {claim.text}")
            if turn.guard_flags:
                print(f"    [flagged numbers] {turn.guard_flags}")
            if turn.unquoted_evidence:
                print(f"    [unverified quotes] {turn.unquoted_evidence}")
        total = sum(t.estimated_cost_usd or 0.0 for t in turns)
        print(f"\ndebate cost: ${total:.4f}")
        print("--- end Bull/Bear Debate ---\n")
    elif result.get("debate_terminated_by"):
        print(
            f"\n[debate] skipped: {result['debate_terminated_by']} — this run "
            f"carries no adversarial review of its analyst findings\n"
        )

    memo = result["decision_memo"]
    print(json.dumps(memo.model_dump(mode="json"), indent=2))
    return result


def _save_vault_artifacts(result: dict, run_log: str) -> list:
    """Write the run's artifacts once the terminal log is complete.

    Saved here rather than inside the nodes for two reasons: the log is only
    whole at the end of the run, and a resumed or already-completed run
    replays state without executing any node, which would otherwise write no
    artifact at all for a run the user just asked for.
    """
    saved = []
    digest = result.get("news_digest")
    sentiment = result.get("sentiment_summary")
    has_sentiment = digest is not None and sentiment is not None

    if has_sentiment:
        saved.append(
            save_sentiment_report(
                digest,
                sentiment,
                issues=result.get("news_digest_issues") or [],
                provenance=run_log,
            )
        )

    turns = result.get("debate_turns") or []
    if turns:
        saved.append(
            save_debate_transcript(
                result["ticker"],
                turns,
                result.get("debate_terminated_by") or "",
            )
        )

    memo = result.get("decision_memo")
    if memo is not None:
        # The log is written exactly once per run. It rides with the
        # sentiment report when there is one, and falls back to the memo
        # otherwise (e.g. `--only technical`) so a run never loses its trace.
        # Both land in the same dated folder, so the log is beside either.
        saved.append(
            save_decision_memo(memo, provenance=None if has_sentiment else run_log)
        )
    return saved


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
    parser.add_argument(
        "--only",
        action="append",
        choices=ALL_ANALYSTS,
        metavar="ANALYST",
        help=(
            "Run only this analyst; repeat to select several "
            f"(choices: {', '.join(ALL_ANALYSTS)}). Default: all of them. "
            "The synthesizer still runs and records the others as data gaps."
        ),
    )
    args = parser.parse_args()

    # The capture wraps the whole run so the provenance file holds the real
    # terminal session — node progress on stdout and the research agent's
    # traces on stderr, interleaved in the order they actually happened.
    # The "saved to" lines below are printed after the log is read, so they
    # are the only run output the file does not contain.
    with capture_terminal_log() as run_log:
        result = asyncio.run(
            run(args.ticker, args.thread_id, args.as_of, args.only)
        )
        saved = _save_vault_artifacts(result, run_log())

    for path in saved:
        print(f"[vault] saved {path}")


if __name__ == "__main__":
    main()