from langgraph.graph import StateGraph, START, END

from app.agent.trading.application.debate_nodes import (
    bear_turn_node,
    bull_turn_node,
    debate_close_node,
)
from app.agent.trading.application.debate_router import next_debate_step
from app.agent.trading.application.nodes import (
    fundamentals_node,
    technical_node,
    news_node,
    sentiment_node,
    risk_node,
    synthesizer_node,
)
from app.agent.trading.domain.trading_state import TradingState

# One entry per analyst as the CLI exposes it; the value is that analyst's
# node chain in run order. "news" is two nodes because the deterministic
# sentiment aggregation is part of the same analyst — it reads news_digest
# and nothing else, so it is never independently selectable.
ANALYST_CHAINS = {
    "fundamentals": (("fundamentals", fundamentals_node),),
    "technical": (("technical", technical_node),),
    "news": (("news", news_node), ("sentiment", sentiment_node)),
}
ALL_ANALYSTS = tuple(ANALYST_CHAINS)

# The tail is no longer one chain. The debate is a CYCLE — bull and bear
# alternate under a conditional edge until the router says stop — and a cycle
# cannot be expressed as a zip(chain, chain[1:]) edge pair, which is why this
# builder grew a second shape rather than one more tuple entry.
DEBATE_NODES = (("bull_turn", bull_turn_node), ("bear_turn", bear_turn_node))

# debate_close/risk/synthesizer always run: the memo is the pipeline's output
# contract, and a partial run should still say what it did and did not see.
# debate_close is first because it is the single point every exit path from
# the cycle passes through, which is where the termination reason gets
# recorded.
POST_DEBATE_NODES = (
    ("debate_close", debate_close_node),
    ("risk", risk_node),
    ("synthesizer", synthesizer_node),
)


def build_trading_graph(checkpointer, interrupt_after=None, analysts=None):
    """`interrupt_after` takes a list of node names to stop after, e.g.
    ["technical"]. Used by the checkpoint round-trip test to stop the graph
    deterministically at a node boundary.

    Two things that were true before Phase 5 and are not any more:

      * "The stub nodes downstream have no I/O to await and complete within
        microseconds of each other, so there is no wall-clock window in which
        an OS signal could land between them." `bull_turn` and `bear_turn`
        make network calls taking seconds. That window is now wide, which is
        what makes a `kill -9` resume test meaningful rather than a race that
        cannot be hit.
      * `interrupt_after` on a CYCLIC node interrupts after EVERY execution of
        it. `interrupt_after=["bull_turn"]` stops after turn 0, then turn 2,
        then turn 4 — three separate resumes, not "stop once here". That is a
        legitimate test tool, but read three interrupts as three interrupts,
        not as a runaway.

    Existing pre-Phase-5 threads are unresumable: the node name `debate` no
    longer exists in this graph. Use a fresh --thread-id.

    `analysts` selects which analyst legs run, e.g. ["news"]; None runs all of
    them. Selection order is ignored — legs always run in ANALYST_CHAINS order
    so that a subset run is a strict subsequence of the full run, and any
    later cross-analyst dependency holds in both."""
    unknown = sorted(set(analysts or ()) - set(ALL_ANALYSTS))
    if unknown:
        raise ValueError(
            f"unknown analyst(s): {', '.join(unknown)} — "
            f"choose from {', '.join(ALL_ANALYSTS)}"
        )
    selected = (
        ALL_ANALYSTS
        if analysts is None
        else tuple(a for a in ALL_ANALYSTS if a in set(analysts))
    )
    if not selected:
        raise ValueError("at least one analyst must be selected")

    builder = StateGraph(TradingState)

    analyst_chain = [node for a in selected for node in ANALYST_CHAINS[a]]
    tail = list(POST_DEBATE_NODES)

    for name, fn in analyst_chain + list(DEBATE_NODES) + tail:
        builder.add_node(name, fn)

    builder.add_edge(START, analyst_chain[0][0])
    for (prev, _), (nxt, _) in zip(analyst_chain, analyst_chain[1:]):
        builder.add_edge(prev, nxt)

    # The ENTRY edge is conditional too, not only the loop-back edges. That is
    # what lets the router skip the debate entirely when no analyst ran and
    # there is no evidence pack to argue over; a plain edge into bull_turn
    # would execute one turn before any router ever saw the state.
    #
    # Both debate nodes get the FULL route map, including the bull -> bull
    # branch that correct alternation never takes. If it ever fires, the
    # result is a visible loop in the checkpoint history that the alternation
    # assert in debate_nodes then names precisely — not a KeyError deep in
    # LangGraph routing that reads as a framework bug.
    route_map = {"bull": "bull_turn", "bear": "bear_turn", "done": tail[0][0]}
    for src in (analyst_chain[-1][0], "bull_turn", "bear_turn"):
        builder.add_conditional_edges(src, next_debate_step, route_map)

    for (prev, _), (nxt, _) in zip(tail, tail[1:]):
        builder.add_edge(prev, nxt)
    builder.add_edge(tail[-1][0], END)

    return builder.compile(
        checkpointer=checkpointer, interrupt_after=interrupt_after or []
    )
