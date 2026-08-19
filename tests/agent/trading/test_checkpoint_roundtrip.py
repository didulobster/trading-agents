"""Checkpoint fidelity for the custom domain types in TradingState.

`ALLOWED_MSGPACK_MODULES` is what restricts checkpoint deserialization to known
types. The failure it guards against is real but delayed: a new domain type
lands in TradingState, everything works in-process while the object is still in
memory, and the break only surfaces when a *different* process reads that
checkpoint back out of Postgres.

Note the enforcement comes from passing `allowed_msgpack_modules` explicitly,
NOT from the LANGGRAPH_STRICT_MSGPACK environment variable. That variable is
read once into a module-level constant when langgraph is first imported, so
checkpointer.py setting it afterwards has no effect, and langgraph consults it
only for serializers built *without* an explicit allowlist. Asserting the
variable would therefore prove nothing about whether anything is enforced —
`test_build_serde_blocks_a_type_outside_the_allowlist` checks the behaviour
instead.

Two tiers here, because they have different costs:

  * The serde tests need no database and run everywhere. They cover the actual
    regression — a domain type reachable from TradingState that nobody
    registered — and fail the moment a future phase adds one.
  * The graph test needs Postgres and skips without it. It exercises the whole
    path (real graph, real checkpointer, real Postgres) across two separate
    checkpointer connections.

Interrupting the graph is done with LangGraph's own `interrupt_after` rather
than an OS signal. The stub nodes downstream of `technical` are print
statements with nothing to await, so they all complete within microseconds of
one another — there is no wall-clock window in which a Ctrl+C could land
between them, which makes process-killing untestable rather than merely
awkward. `interrupt_after` stops at a node boundary deterministically.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from enum import Enum
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

import pandas as pd
import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

import app.agent.trading.application.nodes as nodes
from app.agent.trading.domain.fundamentals_report import FundamentalsReport
from app.agent.trading.domain.technical_report import TechnicalIndicators, TechnicalReport
from app.agent.trading.domain.trading_state import TradingState
from app.agent.trading.infrastructure.checkpointer import (
    ALLOWED_MSGPACK_MODULES,
    DB_URI,
    build_checkpointer,
    build_serde,
)
from app.agent.trading.infrastructure.graph import build_trading_graph

FIXTURE = Path(__file__).resolve().parents[3] / "tests/fixtures/avgo_ohlcv_sample.csv"


def _sample_report() -> TechnicalReport:
    """Includes a None indicator and a populated flagged-numbers list so the
    round-trip covers the optional and collection fields too, not just floats."""
    return TechnicalReport(
        ticker="ACN",
        as_of_date=date(2026, 8, 19),
        data_source="yfinance",
        bars_used=252,
        indicators=TechnicalIndicators(
            sma_50=330.1245,
            sma_200=None,
            rsi_14=41.2033,
            macd=-2.4471,
            macd_signal=-1.2313,
            macd_histogram=-1.2157936592253513,
            last_close=327.55,
            volume_vs_20d_avg=0.8842,
        ),
        interpretation="Momentum is bearish; the histogram sits at around -1.22.",
        interpretation_flagged_numbers=["812"],
    )


# ---------------------------------------------------------------------------
# Tier 1 — serde only. No database.
# ---------------------------------------------------------------------------

def test_technical_report_survives_msgpack_roundtrip():
    """The registered-type path: dump and reload a TechnicalReport through
    build_serde() — the same serializer the checkpointer uses in production,
    not an equivalent rebuilt here."""
    serde = build_serde()
    report = _sample_report()

    restored = serde.loads_typed(serde.dumps_typed(report))

    assert restored == report
    assert isinstance(restored, TechnicalReport)
    assert isinstance(restored.indicators, TechnicalIndicators)
    # the fields most likely to degrade quietly: full float precision, a None
    # optional, a date, and a list
    assert restored.indicators.macd_histogram == -1.2157936592253513
    assert restored.indicators.sma_200 is None
    assert restored.as_of_date == date(2026, 8, 19)
    assert restored.interpretation_flagged_numbers == ["812"]


def test_full_trading_state_survives_msgpack_roundtrip():
    """A whole TradingState dict, as the checkpointer actually stores it —
    two custom report types nested in one payload."""
    serde = build_serde()
    state: TradingState = {
        "ticker": "ACN",
        "fundamentals_report": FundamentalsReport(
            ticker="ACN",
            summary="# Memo",
            input_tokens=1,
            cache_write_tokens=2,
            cache_read_tokens=3,
            output_tokens=4,
            generated_at=date(2026, 8, 19),
        ),
        "technical_report": _sample_report(),
    }

    restored = serde.loads_typed(serde.dumps_typed(state))

    assert restored == state
    assert restored["technical_report"].indicators.rsi_14 == 41.2033


class _UnregisteredModel(BaseModel):
    value: int


def test_build_serde_blocks_a_type_outside_the_allowlist():
    """Proves the *production* serializer enforces the allowlist, not merely
    that registered types survive a round-trip.

    Without this, every test above would keep passing if build_serde() ever
    stopped passing `allowed_msgpack_modules`: langgraph's default in that
    case is permissive — it warns and allows unregistered types — so the
    registered types would still round-trip cleanly while the guard had
    silently become a no-op. This is the test that fails in that scenario.
    """
    serde = build_serde()

    restored = serde.loads_typed(serde.dumps_typed(_UnregisteredModel(value=7)))

    assert isinstance(restored, dict)
    assert restored == {"value": 7}


def test_unregistered_top_level_type_degrades_to_a_dict_without_raising():
    """Negative control, and a documented surprise: an unregistered type does
    not raise on load. It is logged as blocked and comes back as a plain
    dict, so a resumed run hands a dict to a node that expects a
    TechnicalReport and fails later with an AttributeError somewhere in the
    graph rather than a clear serialization error at the read.

    This is what makes the registration list easy to get wrong and its
    breakage hard to trace — and it is why the test above asserts
    `isinstance`, not just equality.
    """
    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[
            entry for entry in ALLOWED_MSGPACK_MODULES if entry[1] != "TechnicalReport"
        ]
    )

    restored = serde.loads_typed(serde.dumps_typed(_sample_report()))

    assert isinstance(restored, dict)
    assert not isinstance(restored, TechnicalReport)


def test_unregistered_nested_type_still_round_trips():
    """The other half of the picture, and the reason the structural test
    below cannot be replaced by a round-trip: with TechnicalIndicators
    unregistered but its parent registered, the payload survives intact —
    pydantic revalidates the parent and rebuilds the child from its dict, so
    nothing observable breaks.

    Registering nested types is therefore belt-and-braces rather than load-
    bearing on this path. Asserted so that a future reader doesn't conclude
    from a passing round-trip that the registration list is complete.
    """
    serde = JsonPlusSerializer(
        allowed_msgpack_modules=[
            entry
            for entry in ALLOWED_MSGPACK_MODULES
            if entry[1] != "TechnicalIndicators"
        ]
    )
    report = _sample_report()

    restored = serde.loads_typed(serde.dumps_typed(report))

    assert restored == report
    assert isinstance(restored.indicators, TechnicalIndicators)


def _custom_types(annotation, acc: set) -> None:
    """Collect every pydantic model and enum reachable from an annotation,
    descending through generics (list[X], X | None) and nested model fields."""
    if get_origin(annotation) is not None:
        for arg in get_args(annotation):
            _custom_types(arg, acc)
        return
    if not isinstance(annotation, type):
        return
    if issubclass(annotation, BaseModel):
        if annotation in acc:
            return
        acc.add(annotation)
        for field in annotation.model_fields.values():
            _custom_types(field.annotation, acc)
    elif issubclass(annotation, Enum):
        acc.add(annotation)


def test_every_domain_type_reachable_from_trading_state_is_registered():
    """The structural guard, and the one that earns its keep over time.

    A round-trip test cannot cover this on its own: per the two tests above,
    an unregistered *top-level* type degrades to a dict (caught), while an
    unregistered *nested* type round-trips cleanly (invisible). Walking
    TradingState catches both, so a report type added in a later phase
    without a matching ALLOWED_MSGPACK_MODULES entry fails here immediately
    rather than in whichever process first resumes a checkpoint.

    Deliberately stricter than the serde path strictly requires, since it
    also demands nested types be registered. That costs one line per type
    and removes the need to reason about which position a type will appear
    in before trusting a checkpoint.
    """
    found: set = set()
    for annotation in get_type_hints(TradingState).values():
        _custom_types(annotation, found)

    registered = {tuple(entry) for entry in ALLOWED_MSGPACK_MODULES}
    missing = {(t.__module__, t.__name__) for t in found} - registered

    assert missing == set(), (
        f"these types are reachable from TradingState but absent from "
        f"ALLOWED_MSGPACK_MODULES: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# Tier 2 — the full graph against real Postgres. Skipped without a database.
# ---------------------------------------------------------------------------

def _postgres_reachable() -> bool:
    """Probe directly with a short timeout. The pool in build_checkpointer
    retries for 30s before giving up, which would stall the suite on every
    run in an environment that simply has no database."""
    if not DB_URI:
        return False
    try:
        import psycopg

        with psycopg.connect(DB_URI, connect_timeout=2):
            return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="needs the checkpoint Postgres at TRADING_CHECKPOINT_DB_URI",
)


def _stub_expensive_nodes(monkeypatch, tmp_path) -> None:
    """Replace the network and vault I/O, keep everything else real.

    compute_indicators still runs for real over the frozen 252-bar fixture, so
    the TechnicalReport being checkpointed carries genuine float values rather
    than round numbers that could mask a precision loss in the round-trip.
    """
    # utc=True is required, not incidental: the fixture spans a DST change, so
    # its timestamps carry mixed -04:00/-05:00 offsets and both `parse_dates`
    # and `format="ISO8601"` leave the index as strings. technical_node calls
    # df.index[-1].date(), which needs real Timestamps. Midnight-local to UTC
    # is a same-day shift at both offsets, so as_of_date is unaffected.
    df = pd.read_csv(FIXTURE, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)

    async def fake_fundamentals(ticker: str):
        return FundamentalsReport(
            ticker=ticker,
            summary="# Stub memo",
            input_tokens=0,
            cache_write_tokens=0,
            cache_read_tokens=0,
            output_tokens=0,
            generated_at=date(2026, 8, 19),
        )

    async def fake_price_history(ticker: str):
        return df, "fixture"

    async def fake_interpret(ticker: str, indicators):
        return "Stub interpretation, no numbers.", []

    monkeypatch.setattr(nodes, "get_fundamentals_report", fake_fundamentals)
    monkeypatch.setattr(nodes, "get_price_history", fake_price_history)
    monkeypatch.setattr(nodes, "interpret_indicators", fake_interpret)
    monkeypatch.setattr(
        nodes, "save_technical_report", lambda report: tmp_path / "stub.md"
    )


@requires_postgres
def test_technical_report_survives_interrupt_and_a_fresh_checkpointer(
    monkeypatch, tmp_path
):
    """Phase 1 stops the graph after `technical` and closes the checkpointer.
    Phase 2 opens a *new* checkpointer connection and a *new* compiled graph,
    which is what forces an actual deserialize from Postgres rather than a
    read of an object still resident in memory — the process-A-writes,
    process-B-reads case ALLOWED_MSGPACK_MODULES protects.
    """
    _stub_expensive_nodes(monkeypatch, tmp_path)
    thread_id = f"test-checkpoint-roundtrip-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    async def phase_1():
        async with build_checkpointer() as checkpointer:
            graph = build_trading_graph(checkpointer, interrupt_after=["technical"])
            await graph.ainvoke({"ticker": "ACN"}, config=config)
            snapshot = await graph.aget_state(config)
            return snapshot.values["technical_report"], snapshot.next

    async def phase_2():
        async with build_checkpointer() as checkpointer:
            graph = build_trading_graph(checkpointer)
            snapshot = await graph.aget_state(config)
            resumed = snapshot.values["technical_report"]
            final = await graph.ainvoke(None, config=config)
            return resumed, final

    async def cleanup():
        """Every run writes a thread to the real checkpoint database, so drop
        it afterwards — otherwise the dev DB accumulates one dead thread per
        test run, and a checkpoint table full of test rows is exactly the
        kind of noise that makes a real resume harder to inspect later."""
        async with build_checkpointer() as checkpointer:
            await checkpointer.adelete_thread(thread_id)

    try:
        before, next_nodes = asyncio.run(phase_1())
        # confirms the interrupt landed exactly where intended, not a node
        # early or late — without this the test could pass on a graph that
        # never ran
        assert next_nodes == ("news",)
        assert before is not None

        after, final = asyncio.run(phase_2())

        assert isinstance(after, TechnicalReport)
        assert after == before
        assert after.indicators.rsi_14 == before.indicators.rsi_14
        assert after.indicators.macd_histogram == before.indicators.macd_histogram
        assert after.bars_used == before.bars_used
        # the resumed run reaches the end and still sees the checkpointed report
        assert final["decision_memo"].technical_signal == before.interpretation
    finally:
        asyncio.run(cleanup())
