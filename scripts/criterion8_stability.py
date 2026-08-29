"""Phase 9 criterion 8 — verdict-direction stability across independent runs.

The one criterion never run in either battery. It re-runs tickers the battery
already ran, at the same `as_of`, on FRESH threads (not resumes), and asks
whether the verdict direction comes back the same.

Separate from `run_p9_battery.py` for one concrete reason: that script writes
`<ticker>.stdout` into the battery's own output directory, so re-running AVGO
through it would overwrite the AVGO log the battery produced. The evidence for
a criterion must not destroy the evidence it is being compared against. This
writes into `<battery>/c8/` and leaves the battery's artifacts untouched.

Real fundamentals, not `MOCK_FUNDAMENTALS` — the criterion is about the whole
system's stability, and a cached fundamentals report would hold the largest
single source of run-to-run variation fixed. That means the FastAPI app must
be up; `preflight()` checks it before spending anything.

Usage:
    uv run python scripts/criterion8_stability.py --as-of 2026-08-28 \
        --tickers AVGO NFLX
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

import os  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_p9_battery import (  # noqa: E402
    MODEL_ENV_VARS,
    _git,
    _package_versions,
    preflight,
    run_one,
)

from app.agent.trading.domain.validation import BatteryManifest  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", type=date.fromisoformat, required=True)
    ap.add_argument("--tickers", nargs="*", default=["AVGO", "NFLX"])
    ap.add_argument("--suffix", default="-c8")
    ap.add_argument("--max-usd", type=float, default=0.75)
    ap.add_argument("--wall-clock-timeout-s", type=float, default=1800.0)
    args = ap.parse_args()

    if os.environ.get("MOCK_FUNDAMENTALS", "").strip() == "1":
        print(
            "MOCK_FUNDAMENTALS=1 is set. Criterion 8 measures whole-system "
            "stability; a cached fundamentals report freezes the biggest "
            "source of variation. Unset it and re-run.",
            file=sys.stderr,
        )
        return 2

    battery_id = f"p9-{args.as_of.isoformat().replace('-', '')}"
    out_dir = Path("docs/validation") / battery_id / "c8"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / f"manifest{args.suffix}.json"

    dirty = bool(_git("status", "--porcelain"))
    if dirty:
        print(
            "WARNING: working tree is dirty — these runs are not reproducible "
            "from the recorded SHA alone.",
            file=sys.stderr,
        )

    manifest = BatteryManifest(
        battery_id=f"{battery_id}{args.suffix}",
        as_of_date=args.as_of,
        git_sha=_git("rev-parse", "HEAD"),
        git_dirty=dirty,
        model_ids={v: os.environ.get(v, "<unset>") for v in MODEL_ENV_VARS},
        package_versions=_package_versions(),
        max_usd=args.max_usd,
        wall_clock_timeout_s=args.wall_clock_timeout_s,
    )

    problems = preflight()
    if problems:
        print("PREFLIGHT FAILED — nothing was run:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    for ticker in args.tickers:
        thread_id = f"trading-{ticker}-{battery_id}{args.suffix}"
        manifest.runs.append(
            run_one(ticker, thread_id, args.as_of, out_dir,
                    args.max_usd, args.wall_clock_timeout_s)
        )
        manifest_path.write_text(manifest.model_dump_json(indent=2))

    total = sum(r.total_usd or 0.0 for r in manifest.runs)
    print(f"\n=== criterion 8 re-runs: {len(manifest.runs)}, ${total:.4f} total")
    for record in manifest.runs:
        print(
            f"  {record.ticker:5s} verdict={record.verdict} "
            f"quality={record.evidence_quality} agreement={record.verdict_agreement} "
            f"samples={record.verdict_samples} "
            f"usd={record.total_usd}"
        )
    print(f"manifest -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
