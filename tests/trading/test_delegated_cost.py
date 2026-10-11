"""The research agent's tools spend money server-side, and until 2026-08-27
that spend reached nothing — not `docs/cost-log.jsonl`, not
`TradingState.cost_events`, and so not `check_run_guards`.

Measured on the Phase 9 battery at ~28% of a real fundamentals run, which is
what let AVGO cost ~$1.41 against a $1.10 cap without tripping it. These
tests pin Trading's side of the accounting: one cost event per model, and the
guard can see it. The EDGAR side, the header and the per-run accumulator, is
tests/edgar_research/agent/test_delegated_usage.py.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.trading.domain.budget import CostEvent, RunBudget, total_spend
from app.trading.domain.fundamentals_report import FundamentalsReport
from app.shared.token_usage import (
    TokenUsage,
)


@pytest.mark.anyio
async def test_fundamentals_logs_one_tool_event_per_model_at_its_own_rate(monkeypatch):
    from app.edgar_research.fundamentals_memo import FundamentalsMemo
    from app.shared.cost import UsageSummary, compute_cost
    from app.trading.infrastructure import fundamentals_port as port

    async def fake_memo(ticker, as_of, **_):
        return FundamentalsMemo(
            text="# memo", model="gpt-5.6-luna", usage=UsageSummary(), provenance="",
            tool_usage=[
                ("deepseek-v4-flash", TokenUsage(input_tokens=115_681, output_tokens=11_750)),
                ("gpt-5.6-luna", TokenUsage(input_tokens=2_000, output_tokens=300)),
            ],
        )

    logged = []

    def fake_log_cost(ticker, mode, usage, model, *, run_id=None, event_id=None):
        logged.append((mode, model))
        return compute_cost(usage, model)

    monkeypatch.setattr(port, "_USE_MOCK", False)
    monkeypatch.setattr(port, "write_fundamentals_memo", fake_memo)
    monkeypatch.setattr(port, "log_cost", fake_log_cost)
    monkeypatch.setattr(port, "save_output", lambda *a, **k: "vault/path")

    report = await port.get_fundamentals_report("ACN", date(2026, 8, 19), run_id="r1")

    by_model = {e.model: e for e in report.tool_cost_events}
    assert set(by_model) == {"deepseek-v4-flash", "gpt-5.6-luna"}
    assert ("trading-fundamentals-tools", "deepseek-v4-flash") in logged
    # Priced at DeepSeek's rate, not the agent's: 115681*0.44 + 11750*1.32.
    assert by_model["deepseek-v4-flash"].usd == pytest.approx(0.066410, abs=1e-6)


def test_a_report_with_the_old_single_tool_event_keeps_its_spend():
    """The fundamentals caches and pre-change checkpoints carry one
    `tool_cost_event`. Ignored as an unknown field, a resumed run would lose
    that spend from its ledger."""
    event = CostEvent(
        event_id="fundamentals-tools:x", node="fundamentals-tools", model="m",
        input_tokens=1, output_tokens=1, cache_creation_input_tokens=0,
        cache_read_input_tokens=0, usd=0.25,
    )
    report = FundamentalsReport.model_validate({
        "ticker": "ACN", "summary": "s", "input_tokens": 0, "cache_write_tokens": 0,
        "cache_read_tokens": 0, "output_tokens": 0, "generated_at": "2026-09-11",
        "tool_cost_event": event.model_dump(),
    })
    assert report.tool_cost_events == [event]


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# The property that actually broke: the run-level guard has to SEE it.
# ---------------------------------------------------------------------------

def test_delegated_spend_counts_against_the_run_budget():
    """AVGO's real cost was ~$1.41 against a $1.10 cap and the guard never
    fired, because the delegated share never entered `cost_events`. With
    both events in the ledger, `total_spend` reflects the real number."""
    own = CostEvent(
        event_id="fundamentals:aaa", node="fundamentals", model="m",
        input_tokens=918, output_tokens=22063, cache_creation_input_tokens=94795,
        cache_read_input_tokens=1408914, usd=0.3706,
    )
    delegated = CostEvent(
        event_id="fundamentals-tools:bbb", node="fundamentals-tools", model="m",
        input_tokens=206320, output_tokens=20000, cache_creation_input_tokens=0,
        cache_read_input_tokens=0, usd=0.3759,
    )

    assert total_spend([own]) == pytest.approx(0.3706)
    assert total_spend([own, delegated]) == pytest.approx(0.7465)

    budget = RunBudget(max_usd=0.60, deadline_utc="2030-01-01T00:00:00Z")
    assert total_spend([own]) < budget.max_usd          # the old blind spot
    assert total_spend([own, delegated]) > budget.max_usd  # now visible


# ---------------------------------------------------------------------------
# `from_response` is the one link that could not be verified against a live
# call: the account ran out of credits mid-session, so every real /ask
# returned 400 before producing a usage object. The header path itself WAS
# verified live end to end (FastAPI emits it, the client parses it) using an
# empty-retrieval question, which returns before any LLM call and correctly
# reports zeros. These pin the non-zero case.
# ---------------------------------------------------------------------------

class _Usage:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_reads_a_real_anthropic_usage_object():
    usage = TokenUsage.from_response(
        _Usage(input_tokens=5158, output_tokens=487,
               cache_creation_input_tokens=0, cache_read_input_tokens=0)
    )
    assert usage.input_tokens == 5158
    assert usage.output_tokens == 487
    assert not usage.is_empty


def test_missing_cache_fields_read_as_zero_not_as_an_error():
    """Responses from calls that set no `cache_control` — which is every
    call this covers today — carry no cache attributes at all."""
    usage = TokenUsage.from_response(_Usage(input_tokens=10, output_tokens=2))
    assert usage.cache_write_tokens == 0
    assert usage.cache_read_tokens == 0


def test_a_none_valued_token_field_reads_as_zero():
    """The SDK reports None rather than 0 for cache fields on some
    responses; `or 0` in from_response covers it, and this pins that."""
    usage = TokenUsage.from_response(
        _Usage(input_tokens=10, output_tokens=2,
               cache_creation_input_tokens=None, cache_read_input_tokens=None)
    )
    assert usage.cache_write_tokens == 0
