"""The fundamentals leg is bounded at the run's analysis date.

Every other source in the pipeline enforces `as_of_date`: prices and news
both refuse to run without it, and the synthesizer refuses to date a memo by
the wall clock. The fundamentals leg — the one whose output carries the most
weight in the memo — never received the date at all. `get_fundamentals_report`
had no `as_of` parameter; it called `date.today()` for the task prompt and
for `generated_at`. So a `--as-of 2026-03-01` run bounded its prices and news
at March, let its analyst read whatever had been filed since, and said
nothing about it in the memo.

The bound itself is enforced in EDGAR Research's tools
(tests/edgar_research/agent/test_tools_as_of.py); these pin Trading's side:
the node passes the date, and the report and cache are keyed on it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import app.trading.application.nodes as nodes
from app.trading.domain.fundamentals_report import FundamentalsReport
from app.trading.infrastructure import fundamentals_port as port

AS_OF = date(2026, 3, 1)


# ---------------------------------------------------------------------------
# The node will not run unbounded
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_the_node_refuses_to_run_without_an_analysis_date():
    with pytest.raises(ValueError) as exc:
        await nodes.fundamentals_node({"ticker": "ACN"})
    assert "lookahead" in str(exc.value)


@pytest.mark.anyio
async def test_the_node_passes_the_date_to_the_port(monkeypatch):
    seen = {}

    async def fake(ticker, as_of, **kw):
        seen["ticker"], seen["as_of"] = ticker, as_of
        return None

    monkeypatch.setattr(nodes, "get_fundamentals_report", fake)
    await nodes.fundamentals_node({"ticker": "ACN", "as_of_date": AS_OF})
    assert seen == {"ticker": "ACN", "as_of": AS_OF}


# ---------------------------------------------------------------------------
# The port dates the report by the analysis date, and caches by it
# ---------------------------------------------------------------------------

def test_the_cache_is_keyed_on_the_date_as_well_as_the_ticker():
    """On ticker alone, MOCK_FUNDAMENTALS paired an August memo with a
    March run."""
    assert port._cache_path("ACN", AS_OF) != port._cache_path("ACN", date(2026, 8, 1))
    assert "2026-03-01" in port._cache_path("ACN", AS_OF).name


@pytest.mark.anyio
async def test_the_report_is_dated_by_the_analysis_date_not_the_wall_clock(monkeypatch):
    from app.edgar_research.fundamentals_memo import FundamentalsMemo
    from app.shared.cost import UsageSummary

    captured = {}

    async def fake_memo(ticker, as_of, **_):
        captured["as_of"] = as_of
        return FundamentalsMemo(
            text="# memo", model="m", usage=UsageSummary(), tool_usage=[], provenance="",
        )

    monkeypatch.setattr(port, "_USE_MOCK", False)
    monkeypatch.setattr(port, "write_fundamentals_memo", fake_memo)
    monkeypatch.setattr(port, "log_cost", lambda *a, **k: 0.01)
    monkeypatch.setattr(port, "save_output", lambda *a, **k: "vault/path")
    monkeypatch.setattr(port, "_CACHE_DIR", __import__("pathlib").Path("/tmp/_fundamentals_test"))

    report = await port.get_fundamentals_report("ACN", AS_OF, run_id="r1")

    assert report.generated_at == AS_OF != date.today()
    assert captured["as_of"] == AS_OF


# ---------------------------------------------------------------------------
# The memo says the run was historical
# ---------------------------------------------------------------------------

def _report() -> FundamentalsReport:
    return FundamentalsReport(
        ticker="ACN", summary="# memo", input_tokens=0, cache_write_tokens=0,
        cache_read_tokens=0, output_tokens=0, generated_at=AS_OF,
    )


def test_a_historical_run_says_the_models_own_priors_are_not_bounded():
    gaps = nodes._fundamentals_caveats(
        {"as_of_date": AS_OF, "fundamentals_report": _report()}
    )
    assert len(gaps) == 1
    assert "2026-03-01" in gaps[0] and "prior knowledge is not bounded" in gaps[0].replace("\n", " ")


def test_a_run_dated_today_has_no_after_to_leak():
    gaps = nodes._fundamentals_caveats(
        {"as_of_date": date.today(), "fundamentals_report": _report()}
    )
    assert gaps == []


def test_a_run_whose_fundamentals_leg_did_not_run_says_nothing_about_it():
    """That absence is already reported by the analyst-did-not-run gap."""
    assert nodes._fundamentals_caveats({"as_of_date": AS_OF - timedelta(days=1)}) == []
