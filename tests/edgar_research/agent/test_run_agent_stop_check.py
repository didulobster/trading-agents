"""The Research agent's loop stops when its stop check fires.

`run_agent` calls `stop_check` before every model turn and every wave of
tool calls; a reason stops the loop and forces a memo from what was
gathered. Trading supplies the check through `write_fundamentals_memo` to
apply its run budget inside the fundamentals node — see
tests/trading/test_in_node_budget_guard.py for that side.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.edgar_research.agent.researcher as researcher


def _usage(out: int = 10):
    return SimpleNamespace(
        input_tokens=0, output_tokens=out,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )


def _tool_use(i: int):
    return SimpleNamespace(type="tool_use", id=f"t{i}", name="check_corpus", input={"ticker": "ACN"})


def _text(content) -> str:
    """A turn's text, whether it is a bare string or content blocks.

    Every call now goes through `_roll_cache_breakpoint`, which wraps a
    string turn so the breakpoint has a block to attach to.
    """
    if isinstance(content, str):
        return content
    return " ".join(
        b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
    )


class FakeAgentClient:
    """Answers every turn with tool calls, and the forced-memo turn (the one
    whose last message is the budget note) with a memo."""

    def __init__(self, tools_per_turn: int = 1):
        self.tools_per_turn = tools_per_turn
        self.calls: list[list[dict]] = []
        self.requests: list[dict] = []
        self.messages = self

    async def create(self, **kwargs):
        messages = kwargs["messages"]
        self.calls.append(messages)
        self.requests.append(kwargs)
        last = _text(messages[-1]["content"])
        if "Write the memo now" in last:
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="# ACN memo\n## Assessment\nstub")],
                stop_reason="end_turn", usage=_usage(),
            )
        n = len(self.calls)
        return SimpleNamespace(
            content=[_tool_use(n * 10 + k) for k in range(self.tools_per_turn)],
            stop_reason="tool_use", usage=_usage(),
        )


@pytest.fixture
def agent(monkeypatch):
    client = FakeAgentClient()
    executed: list[str] = []

    async def fake_execute(name, inputs):
        executed.append(name)
        return "ok"

    monkeypatch.setattr(researcher, "get_client", lambda model: client)
    monkeypatch.setattr(researcher, "execute_tool", fake_execute)
    return SimpleNamespace(client=client, executed=executed)


@pytest.mark.anyio
async def test_the_loop_stops_when_the_check_fires_and_still_writes_a_memo(agent):
    # Each model call reports 10 output tokens. The check allows turn 1 and
    # its tool (usage 10), then fires at usage 20: turn 2's tool call is
    # refused, and the next turn never starts — the forced memo runs instead.
    stop = lambda usage: "budget_exceeded" if usage.output_tokens >= 20 else None

    memo, usage = await researcher.run_agent("task", "system", stop_check=stop)

    assert memo.startswith("# ACN memo")
    assert len(agent.client.calls) == 3        # turn 1, turn 2, forced memo
    assert agent.executed == ["check_corpus"]  # turn 2's tool was refused
    refused = agent.client.calls[2][-2]["content"][0]["content"]
    assert refused.startswith("RUN BUDGET REACHED: budget_exceeded")
    assert "spending or time budget has been reached (budget_exceeded)" in _text(
        agent.client.calls[2][-1]["content"]
    )
    assert usage.output_tokens == 30


@pytest.mark.anyio
async def test_a_breach_before_the_first_turn_spends_only_the_memo_call(agent):
    await researcher.run_agent("task", "system", stop_check=lambda usage: "deadline_exceeded")

    assert len(agent.client.calls) == 1
    assert agent.executed == []


@pytest.mark.anyio
async def test_a_breach_mid_turn_refuses_the_remaining_tool_calls(agent, monkeypatch):
    """One turn can carry several tool calls (gpt-5.6-luna sent 6-7
    ask_edgar calls per turn on 2026-09-11), each with its own server-side
    spend — so the check runs before each wave of calls, not only per turn.
    At concurrency 1 a wave is one call: the strictest setting."""
    monkeypatch.setattr(researcher, "TOOL_CONCURRENCY", 1)
    agent.client.tools_per_turn = 3
    stop = lambda usage: "budget_exceeded" if agent.executed else None

    await researcher.run_agent("task", "system", stop_check=stop)

    assert agent.executed == ["check_corpus"]
    results = agent.client.calls[-1][-2]["content"]
    assert [r["content"] == "ok" for r in results] == [True, False, False]
    assert all("RUN BUDGET REACHED" in r["content"] for r in results[1:])


@pytest.mark.anyio
async def test_without_a_check_the_loop_is_unchanged(agent, monkeypatch):
    monkeypatch.setattr(researcher, "MAX_TURNS", 2)

    await researcher.run_agent("task", "system")

    assert len(agent.client.calls) == 3        # both turns, then the MAX_TURNS memo
    assert agent.executed == ["check_corpus", "check_corpus"]
    assert "exhausted your tool-call budget" in _text(agent.client.calls[-1][-1]["content"])
