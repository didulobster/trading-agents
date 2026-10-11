"""The one thing EDGAR Research publishes to other contexts: a fundamentals memo.

Trading imports this module and nothing else from EDGAR Research. The prompt,
the agent's model and the pricing of its tools' server-side calls stay behind
it; what comes out is the memo text and what it cost, in tokens per model.
"""

from dataclasses import dataclass
from datetime import date
from typing import Callable

from app.edgar_research.agent.prompts import ANALYST_SYSTEM_PROMPT
from app.edgar_research.agent.researcher import AGENT_MODEL, run_agent
from app.edgar_research.agent.tools import get_delegated_usage, get_session_log
from app.shared.cost import UsageSummary, compute_cost
from app.shared.token_usage import TokenUsage


@dataclass(frozen=True)
class Spend:
    """What a memo run has spent so far: the agent loop's own tokens, and the
    USD total including what its tools spent server-side."""

    model: str
    usage: UsageSummary
    usd: float


@dataclass(frozen=True)
class FundamentalsMemo:
    """A finished memo and what it cost.

    `tool_usage` is one entry per server-side model, each to be priced at its
    own rate. A list, not a dict: usage from a server that named no model is
    attributed to the agent's model, and must stay a separate entry rather
    than merge into one that did name it.
    """

    text: str
    model: str
    usage: UsageSummary
    tool_usage: list[tuple[str, TokenUsage]]
    provenance: str


async def write_fundamentals_memo(
    ticker: str,
    as_of: date,
    *,
    stop_check: Callable[[Spend], str | None] | None = None,
) -> FundamentalsMemo:
    """Run the full research checklist for `ticker`, bounded at `as_of`.

    The bound is enforced in the tools, not in the prompt: `run_agent` puts
    it in the run state and every filing-reading tool sends `filed_before`
    with it. Wording alone would leave the hole open on any turn the model
    did not think about it.

    `stop_check` sees the run's spend before every model turn and tool wave;
    a non-None reason stops the loop and forces a memo from what was gathered.
    """
    task = (
        f"The analysis date is {as_of.isoformat()}. Run the full research "
        f"checklist for {ticker}. Filing retrieval is bounded at that date, "
        f"so anything filed after it is deliberately unavailable to you — "
        f"report what is missing as a data gap rather than reasoning from "
        f"memory about it."
    )
    check = None
    if stop_check is not None:
        check = lambda usage: stop_check(Spend(AGENT_MODEL, usage, _spend_so_far(usage)))
    text, usage = await run_agent(task, ANALYST_SYSTEM_PROMPT, stop_check=check, as_of=as_of)
    return FundamentalsMemo(
        text=text,
        model=AGENT_MODEL,
        usage=usage,
        tool_usage=_tool_usage(),
        provenance=get_session_log(),
    )


def _spend_so_far(usage: UsageSummary) -> float:
    """The agent loop's own spend plus what its tools spent server-side so
    far, each priced at the model that spent it (a server that did not name
    its model is priced at the agent's, as the final accounting does)."""
    total = compute_cost(usage, AGENT_MODEL) or 0.0
    for model, tool_usage in get_delegated_usage().items():
        total += compute_cost(tool_usage, model or AGENT_MODEL) or 0.0
    return total


def _tool_usage() -> list[tuple[str, TokenUsage]]:
    """What the agent's tools spent server-side, per model.

    The server's models need not be the agent's: pricing a deepseek-served
    /ask at a gpt-5.6-luna agent's rate under-counted it by ~44% on
    2026-09-11, and the budget guard waved through the difference.
    """
    entries = []
    for model, usage in get_delegated_usage().items():
        if usage.is_empty:
            continue
        if model is None:
            print(
                f"[fundamentals] server reported tool usage without a model — "
                f"pricing it at {AGENT_MODEL}, which is wrong if the server's "
                f"answer/extraction models differ. Restart the API server."
            )
            model = AGENT_MODEL
        entries.append((model, usage))
    return entries
