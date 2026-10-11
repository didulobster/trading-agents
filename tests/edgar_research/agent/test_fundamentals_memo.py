"""The published seam: what `write_fundamentals_memo` hands another context."""

from datetime import date

import pytest

import app.edgar_research.fundamentals_memo as fm
from app.edgar_research.agent.tools import record_log_line, reset_run_provenance
from app.shared.cost import UsageSummary
from app.shared.token_usage import TokenUsage

AS_OF = date(2026, 3, 1)


@pytest.fixture(autouse=True)
def _fresh_run(monkeypatch):
    reset_run_provenance()
    monkeypatch.setattr(fm, "get_delegated_usage", lambda: {})


def _fake_run_agent(captured: dict):
    async def run_agent(task, system_prompt, *, stop_check=None, as_of=None):
        captured.update(task=task, as_of=as_of)
        if stop_check is not None:
            captured["stop"] = stop_check(UsageSummary())
        return "# memo", UsageSummary()
    return run_agent


@pytest.mark.anyio
async def test_the_task_and_the_tools_are_bounded_at_the_analysis_date(monkeypatch):
    captured = {}
    monkeypatch.setattr(fm, "run_agent", _fake_run_agent(captured))

    memo = await fm.write_fundamentals_memo("ACN", AS_OF)

    assert "2026-03-01" in captured["task"]
    assert captured["as_of"] == AS_OF
    assert memo.text == "# memo"
    assert memo.model == fm.AGENT_MODEL


@pytest.mark.anyio
async def test_the_stop_check_sees_delegated_spend_priced_at_its_own_model(monkeypatch):
    """1M DeepSeek input tokens are $0.44 at the table's rate — priced as
    DeepSeek regardless of the agent's model, like the final accounting."""
    captured, seen = {}, []
    monkeypatch.setattr(fm, "run_agent", _fake_run_agent(captured))
    monkeypatch.setattr(fm, "get_delegated_usage", lambda: {
        "deepseek-v4-flash": TokenUsage(input_tokens=1_000_000),
    })

    await fm.write_fundamentals_memo(
        "ACN", AS_OF, stop_check=lambda spend: seen.append(spend) or "stop",
    )

    assert captured["stop"] == "stop"
    assert seen[0].usd == pytest.approx(0.44)
    assert seen[0].model == fm.AGENT_MODEL


@pytest.mark.anyio
async def test_tool_usage_is_listed_per_model_and_empty_entries_dropped(monkeypatch):
    monkeypatch.setattr(fm, "run_agent", _fake_run_agent({}))
    monkeypatch.setattr(fm, "get_delegated_usage", lambda: {
        "deepseek-v4-flash": TokenUsage(input_tokens=115_681, output_tokens=11_750),
        "gpt-5.6-luna": TokenUsage(input_tokens=2_000, output_tokens=300),
        "unused-model": TokenUsage(),
    })

    memo = await fm.write_fundamentals_memo("ACN", AS_OF)

    assert [model for model, _ in memo.tool_usage] == ["deepseek-v4-flash", "gpt-5.6-luna"]


@pytest.mark.anyio
async def test_usage_from_a_server_that_named_no_model_goes_to_the_agent_model(monkeypatch):
    monkeypatch.setattr(fm, "run_agent", _fake_run_agent({}))
    monkeypatch.setattr(fm, "get_delegated_usage", lambda: {None: TokenUsage(input_tokens=10)})

    memo = await fm.write_fundamentals_memo("ACN", AS_OF)

    assert [model for model, _ in memo.tool_usage] == [fm.AGENT_MODEL]


@pytest.mark.anyio
async def test_the_provenance_is_the_run_s_session_log(monkeypatch):
    monkeypatch.setattr(fm, "run_agent", _fake_run_agent({}))
    record_log_line("--- turn 1 ---")

    memo = await fm.write_fundamentals_memo("ACN", AS_OF)

    assert "--- turn 1 ---" in memo.provenance


@pytest.fixture
def anyio_backend():
    return "asyncio"
