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


def build_trading_graph(checkpointer, interrupt_after=None):
    """`interrupt_after` takes a list of node names to stop after, e.g.
    ["technical"]. Used by the checkpoint round-trip test to stop the graph
    deterministically at a node boundary — the stub nodes downstream have no
    I/O to await and complete within microseconds of each other, so there is
    no wall-clock window in which an OS signal could land between them."""
    builder = StateGraph(TradingState)

    builder.add_node("fundamentals", fundamentals_node)
    builder.add_node("technical", technical_node)
    builder.add_node("news", news_node)
    builder.add_node("sentiment", sentiment_node)
    builder.add_node("debate", debate_node)
    builder.add_node("risk", risk_node)
    builder.add_node("synthesizer", synthesizer_node)

    builder.add_edge(START, "fundamentals")
    builder.add_edge("fundamentals", "technical")
    builder.add_edge("technical", "news")
    builder.add_edge("news", "sentiment")
    builder.add_edge("sentiment", "debate")
    builder.add_edge("debate", "risk")
    builder.add_edge("risk", "synthesizer")
    builder.add_edge("synthesizer", END)

    return builder.compile(
        checkpointer=checkpointer, interrupt_after=interrupt_after or []
    )