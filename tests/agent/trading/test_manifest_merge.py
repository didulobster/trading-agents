"""Re-running one ticker must not destroy the rest of the battery's record.

Live (2026-08-28): a `--tickers MSFT` invocation rebuilt the manifest from
scratch and replaced four completed runs with one. The evidence survived —
vault memos, cost log and checkpoints are all elsewhere — but the manifest
is what the automated gate and the stability comparison read, so the battery
looked like it had a single run.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.agent.trading.domain.validation import BatteryManifest, RunRecord


def _manifest(*tickers: str) -> BatteryManifest:
    m = BatteryManifest(
        battery_id="p9-20260826", as_of_date=date(2026, 8, 26), git_sha="abc",
        git_dirty=False, model_ids={}, package_versions={},
        max_usd=1.40, wall_clock_timeout_s=1800.0,
    )
    for t in tickers:
        m.runs.append(RunRecord(
            ticker=t, thread_id=f"trading-{t}-p9", as_of_date=date(2026, 8, 26),
            started_at="x", exit_status="ok", verdict="hold", total_usd=0.8,
        ))
    return m


def _carry_forward(prior: BatteryManifest, fresh: BatteryManifest, rerunning: set[str]):
    """Mirrors the runner's merge rule, kept here so the RULE is tested even
    though the runner reads its prior state from disk."""
    fresh.runs.extend(r for r in prior.runs if r.ticker not in rerunning)
    return fresh


def test_untouched_tickers_are_carried_forward():
    prior = _manifest("NFLX", "AVGO", "ACN", "FIG")
    fresh = _manifest()

    merged = _carry_forward(prior, fresh, {"MSFT"})

    assert {r.ticker for r in merged.runs} == {"NFLX", "AVGO", "ACN", "FIG"}


def test_a_rerun_ticker_is_replaced_not_duplicated():
    """Keeping both attempts would make "how many runs completed" ambiguous;
    the newest attempt is the one describing the thread's current state."""
    prior = _manifest("NFLX", "MSFT")
    fresh = _manifest("MSFT")

    merged = _carry_forward(prior, fresh, {"MSFT"})

    assert [r.ticker for r in merged.runs].count("MSFT") == 1
    assert {r.ticker for r in merged.runs} == {"NFLX", "MSFT"}


def test_a_full_battery_rerun_carries_nothing_forward():
    prior = _manifest("NFLX", "AVGO")
    fresh = _manifest("NFLX", "AVGO")

    merged = _carry_forward(prior, fresh, {"NFLX", "AVGO"})

    assert len(merged.runs) == 2


def test_the_merged_manifest_still_round_trips():
    merged = _carry_forward(_manifest("NFLX"), _manifest("MSFT"), {"MSFT"})
    assert BatteryManifest.model_validate_json(merged.model_dump_json()) == merged


def test_the_real_manifest_on_disk_is_intact(tmp_path):
    """Guards the reconstruction itself: the battery's manifest should hold
    every ticker that was run, not just the last one."""
    from pathlib import Path
    p = Path("docs/validation/p9-20260826/manifest-a2.json")
    if not p.exists():
        pytest.skip("battery manifest not present in this checkout")
    m = BatteryManifest.model_validate_json(p.read_text())
    assert {r.ticker for r in m.runs} >= {"NFLX", "AVGO", "ACN", "FIG"}


# ---------------------------------------------------------------------------
# Thread-id overrides on the rebuild path. A run can belong in a battery's
# manifest without following its naming convention — one made by hand, or
# carried over from an earlier experiment at the same as_of. The DeepSeek
# battery of 2026-08-29 is the case: five runs named
# `trading-<T>-p9-20260828-ds` plus an existing MSFT run still called
# `deepseek-v4-verify-3`.
# ---------------------------------------------------------------------------

def test_overrides_parse_into_a_ticker_to_thread_mapping():
    pairs = ["MSFT=deepseek-v4-verify-3", "ACN=some-other-thread"]
    overrides = dict(p.split("=", 1) for p in pairs)
    assert overrides["MSFT"] == "deepseek-v4-verify-3"
    assert overrides["ACN"] == "some-other-thread"


def test_an_override_value_containing_equals_is_kept_whole():
    """split("=", 1) rather than split("=") — a thread id is opaque and may
    legitimately contain the separator."""
    overrides = dict(p.split("=", 1) for p in ["MSFT=a=b"])
    assert overrides["MSFT"] == "a=b"


def test_tickers_without_an_override_keep_the_derived_id():
    overrides = dict(p.split("=", 1) for p in ["MSFT=custom"])
    assert overrides.get("NFLX", "trading-NFLX-p9-20260828-a2") == "trading-NFLX-p9-20260828-a2"
