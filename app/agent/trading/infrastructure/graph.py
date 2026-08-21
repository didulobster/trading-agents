from langgraph.graph import StateGraph, START, END

from app.agent.trading.application.nodes import (
    fundamentals_node,
    technical_node,
    news_node,
    sentiment_node,
    debate_node,
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

# debate/risk/synthesizer always run: the memo is the pipeline's output
# contract, and a partial run should still say what it did and did not see.
TAIL_NODES = (
    ("debate", debate_node),
    ("risk", risk_node),
    ("synthesizer", synthesizer_node),
)


def build_trading_graph(checkpointer, interrupt_after=None, analysts=None):
    """`interrupt_after` takes a list of node names to stop after, e.g.
    ["technical"]. Used by the checkpoint round-trip test to stop the graph
    deterministically at a node boundary — the stub nodes downstream have no
    I/O to await and complete within microseconds of each other, so there is
    no wall-clock window in which an OS signal could land between them.

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

    chain = [node for a in selected for node in ANALYST_CHAINS[a]]
    chain += list(TAIL_NODES)

    for name, fn in chain:
        builder.add_node(name, fn)

    builder.add_edge(START, chain[0][0])
    for (prev, _), (nxt, _) in zip(chain, chain[1:]):
        builder.add_edge(prev, nxt)
    builder.add_edge(chain[-1][0], END)

    return builder.compile(
        checkpointer=checkpointer, interrupt_after=interrupt_after or []
    )
