"""The Research agent's tools bound every filing read at the run's analysis date.

The bound is enforced in the TOOLS, not in the prompt. Wording tells the
model what to do; `filed_before` on every filing-reading call is what makes
it so on the turns the model is not thinking about it. Trading passes the
date in through `write_fundamentals_memo`; see
tests/trading/test_fundamentals_as_of.py for that side.
"""

from __future__ import annotations

from datetime import date

import pytest

import app.edgar_research.agent.tools as tools

AS_OF = date(2026, 3, 1)


@pytest.fixture(autouse=True)
def _fresh():
    tools.reset_run_provenance()
    yield
    tools.reset_run_provenance()


# ---------------------------------------------------------------------------
# The tools carry the bound
# ---------------------------------------------------------------------------

class _Resp:
    status_code = 200
    headers: dict = {}
    text = "{}"

    def json(self):
        return {"answer": "a", "chunks": []}


def _capture(monkeypatch):
    sent = {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **kw):
            sent["url"], sent["json"] = url, json or {}
            return _Resp()

        async def get(self, url, params=None, **kw):
            sent["url"], sent["params"] = url, params or {}
            return _Resp()

    monkeypatch.setattr(tools.httpx, "AsyncClient", lambda **kw: _Client())
    return sent


@pytest.mark.anyio
async def test_ask_edgar_bounds_retrieval_at_the_analysis_date(monkeypatch):
    sent = _capture(monkeypatch)
    tools.reset_run_provenance(AS_OF)

    await tools._dispatch("ask_edgar", {"question": "q", "tickers": ["ACN"]})

    assert sent["json"]["filed_before"] == "2026-03-01"


@pytest.mark.anyio
async def test_check_latest_filings_does_not_reveal_later_filings(monkeypatch):
    """Knowing a 10-K exists is lookahead before a word of it is read."""
    sent = _capture(monkeypatch)
    tools.reset_run_provenance(AS_OF)

    await tools._dispatch("check_latest_filings", {"ticker": "ACN"})

    assert sent["json"]["filed_before"] == "2026-03-01"


@pytest.mark.anyio
async def test_extract_metrics_window_is_clamped_to_the_bound(monkeypatch):
    """The model picks this window; the run's bound caps the top of it."""
    sent = _capture(monkeypatch)
    tools.reset_run_provenance(AS_OF)

    await tools._dispatch("extract_metrics", {
        "ticker": "ACN", "fiscal_period": "FY2026", "filing_type": "10-K",
        "filed_date": "2026-01-15", "filed_before": "2026-12-31",
    })

    assert sent["json"]["filed_before"] == "2026-03-01"


@pytest.mark.anyio
async def test_a_narrower_window_the_model_chose_is_left_alone(monkeypatch):
    sent = _capture(monkeypatch)
    tools.reset_run_provenance(AS_OF)

    await tools._dispatch("extract_metrics", {
        "ticker": "ACN", "fiscal_period": "FY2026", "filing_type": "10-K",
        "filed_date": "2026-01-15", "filed_before": "2026-01-31",
    })

    assert sent["json"]["filed_before"] == "2026-01-31"


@pytest.mark.anyio
async def test_an_unbounded_run_sends_no_bound(monkeypatch):
    """The standalone research CLI answers about now, and its behaviour is
    unchanged."""
    sent = _capture(monkeypatch)
    tools.reset_run_provenance()      # no as_of

    await tools._dispatch("ask_edgar", {"question": "q", "tickers": ["ACN"]})

    assert "filed_before" not in sent["json"]


def test_the_bound_is_not_something_the_model_can_set():
    """A bound the agent has to remember to apply is not a bound.

    `extract_metrics` is the one tool that takes a date window, and that
    window is the model's own extraction choice rather than the run's
    bound — it is clamped, not trusted (see the two tests above). Nothing
    else offers a date argument at all.
    """
    by_name = {t["name"]: t["input_schema"]["properties"] for t in tools.TOOLS}
    for name in ("ask_edgar", "check_latest_filings", "check_corpus", "ingest_ticker"):
        assert "filed_before" not in by_name[name], name
        assert "filed_after" not in by_name[name], name


# ---------------------------------------------------------------------------
# check_corpus: seeing that a filing exists is lookahead too
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_check_corpus_is_bounded_at_the_analysis_date(monkeypatch):
    """Found live. A FIG run at --as-of 2026-03-01 could not READ the later
    filings — ask_edgar and latest-filings were bounded — but check_corpus
    was not, so the agent enumerated them and wrote into its own memo:

      "The corpus also contains filings dated after the analysis cutoff,
       including Form 10-Q filed 2026-05-14 and Form 10-Q filed 2026-08-05"

    Knowing a filing exists, and when, is information from after the cutoff.
    """
    sent = _capture(monkeypatch)
    tools.reset_run_provenance(AS_OF)

    await tools._dispatch("check_corpus", {"ticker": "FIG"})

    assert sent["params"]["filed_before"] == "2026-03-01"


@pytest.mark.anyio
async def test_an_unbounded_run_still_sees_the_whole_corpus(monkeypatch):
    sent = _capture(monkeypatch)
    tools.reset_run_provenance()

    await tools._dispatch("check_corpus", {"ticker": "FIG"})

    assert "filed_before" not in sent["params"]
