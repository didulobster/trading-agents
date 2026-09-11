"""Discrimination probe — does the verdict respond to the evidence at all?

The Phase 9 deepseek battery returned `hold` on all six watchlist tickers,
every one unanimous 3/3, confidence 0.92-0.97. Two readings fit that
equally well: the model is less noisy than Haiku on debates Haiku finds
ambiguous, or the model returns `hold` regardless of input. The exit
criteria as written cannot tell those apart, and criterion 8 (verdict
stability under re-run) cannot either — a system with no discriminating
power is perfectly stable.

This probe separates them by changing the input instead of re-running it.
One channel is manipulated — the fundamentals report — and everything else
(technical indicators, news, sentiment, every prompt, the model, the
sampling) is left exactly as the battery ran it. If the verdict does not
move when the fundamentals evidence is inverted, the verdict is not a
function of the evidence.

WHY THE FUNDAMENTALS TEXT IS THE RIGHT LEVER
--------------------------------------------
`synthesis_port._grounded_corpus` is built from the analyst reports in
state, not from the EDGAR vector store. So a substituted fundamentals
`summary` is grounded by construction: quotes resolve against it, the
number-fabrication guards check against it, and `verify_decision_memo`
passes. The run is internally consistent and every guard behaves normally
— which is the point. This measures response to evidence, not the guards'
reaction to malformed input.

HOW THE VARIANTS ARE BUILT
--------------------------
Not written from scratch. Each variant is the REAL cached report with
named `##` sections replaced and everything else — preamble, filing list,
scope note, untouched sections, the red-flag rubric, the appendices —
carried over verbatim. Length, tone, epistemic tags and structure are
therefore held constant with the baseline, and the manipulation is a
readable diff rather than a new document.

The rubric is never edited. It states the thresholds that decide what a
red flag is, so leaving it untouched means the injected distress is
distress BY THE REPORT'S OWN STANDARD, not by mine.

SAFETY
------
`.fundamentals_cache/` is gitignored, so the real reports the battery
produced exist in exactly one place and a careless overwrite destroys
them. Every swap here backs the original up first, refuses to run if a
backup would be clobbered, and restores in a `finally` — including on
Ctrl-C or a crash mid-run.

Usage:
    uv run python scripts/discrimination_probe.py --arm distressed
    uv run python scripts/discrimination_probe.py --arm distressed --tickers MSFT
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

import os  # noqa: E402

# MOCK_FUNDAMENTALS is read at import time by fundamentals_port, and the
# pipeline runs in a subprocess that inherits this environment. Set before
# anything imports the port.
os.environ["MOCK_FUNDAMENTALS"] = "1"

# Run as a file, sys.path[0] is scripts/ — the repo root (for `app`) and this
# directory (for `run_p9_battery`) both have to be importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_p9_battery import run_one  # noqa: E402

CACHE_DIR = Path("app/agent/trading/.fundamentals_cache")
PROBE_DIR = Path("docs/validation/disc-probe-20260829")
VARIANT_DIR = PROBE_DIR / "variants"
BACKUP_DIR = PROBE_DIR / "backup"

# The battery's as_of, so the baseline this is compared against is the
# battery's own run and not a different day's news.
AS_OF = date(2026, 8, 28)

_SECTION_RE = re.compile(r"^## .+$", re.M)
_FIGURE_ENTRY_RE = re.compile(
    # The context line is optional AND may be the last line in the file with
    # no trailing newline — an earlier version required that newline, so the
    # final entry of an appendix never matched and survived unpruned.
    r"- \*\*(?:figure|quote):\*\* `(.+?)`\n(  - context:(.*?))?(?=\n- \*\*|\n## |\Z)",
    re.S,
)
APPENDIX_HEADINGS = (
    "## Unverified Figures and Quotations",
    "## Unbacked Derivations",
    "## Underived Arithmetic",
)


def split_sections(text: str) -> tuple[str, dict[str, str]]:
    """(preamble, {heading: section_text_including_heading}) in file order."""
    marks = [m.start() for m in _SECTION_RE.finditer(text)]
    if not marks:
        return text, {}
    preamble = text[: marks[0]]
    sections: dict[str, str] = {}
    for i, start in enumerate(marks):
        end = marks[i + 1] if i + 1 < len(marks) else len(text)
        block = text[start:end]
        sections[block.splitlines()[0].strip()] = block
    return preamble, sections


def _norm(text: str) -> str:
    return " ".join(text.split())


def prune_appendices(body: str, appendices: dict[str, str]) -> dict[str, str]:
    """Drop appendix entries whose CONTEXT no longer appears in the body.

    The test is the context snippet, not the bare figure. Two reasons, both
    found the first time this ran:

    - A bare figure matches as a substring of an unrelated number, so `6.5`
      survived on the strength of some other `…6.5…` elsewhere in the file.
    - The snippet quotes the surrounding sentence of the ORIGINAL report.
      An entry kept for a replaced section carries the baseline narrative —
      "Assessment: MIXED, 1 red flag — Free cash flow fell 6.5%" — into the
      variant's corpus verbatim, which is the exact text the manipulation
      exists to remove. That is a leak, not a loose end.

    A snippet is a window around the figure with ellipses at the edges, so
    stripping those leaves a literal substring of the report it came from.
    Entries from untouched sections match and are kept verbatim.
    """
    body_n = _norm(body)
    out = {}
    for heading, block in appendices.items():
        def keep(m: re.Match) -> str:
            context = m.group(3)
            if context is None:
                return m.group(0) if m.group(1) in body else ""
            snippet = _norm(context).strip("… ").strip()
            return m.group(0) if snippet and snippet in body_n else ""

        pruned = _FIGURE_ENTRY_RE.sub(keep, block)
        out[heading] = re.sub(r"\n{3,}", "\n\n", pruned)
    return out


def build_variant(real_summary: str, variant_md: str) -> tuple[str, list[str]]:
    """Splice `variant_md`'s sections into `real_summary`. Returns (text, replaced)."""
    preamble, real_sections = split_sections(real_summary)
    _, new_sections = split_sections(variant_md)

    unknown = [h for h in new_sections if h not in real_sections]
    if unknown:
        raise SystemExit(
            f"variant has sections the real report does not: {unknown}\n"
            f"real headings: {list(real_sections)}"
        )

    merged = {h: new_sections.get(h, block) for h, block in real_sections.items()}
    body = preamble + "".join(
        b for h, b in merged.items() if h not in APPENDIX_HEADINGS
    )
    appendices = prune_appendices(
        body, {h: b for h, b in merged.items() if h in APPENDIX_HEADINGS}
    )
    text = preamble + "".join(
        appendices.get(h, b) for h, b in merged.items()
    )
    return text, sorted(new_sections)


def swap_in(ticker: str, arm: str) -> list[str]:
    """Back up the real cache, write the variant over it. Returns replaced sections."""
    real_path = CACHE_DIR / f"{ticker}.json"
    backup_path = BACKUP_DIR / f"{ticker}.json"
    variant_path = VARIANT_DIR / f"{ticker}-{arm}.md"

    if not real_path.exists():
        raise SystemExit(f"no cached report for {ticker} — nothing to vary")
    if not variant_path.exists():
        raise SystemExit(f"no variant at {variant_path}")
    if backup_path.exists():
        raise SystemExit(
            f"{backup_path} already exists — a previous probe did not restore. "
            "Restore it by hand before running again; do not overwrite it."
        )

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(real_path, backup_path)

    payload = json.loads(real_path.read_text())
    text, replaced = build_variant(payload["summary"], variant_path.read_text())
    payload["summary"] = text
    # Nothing is spent on fundamentals in a mock run. Carrying the original
    # run's cost_event forward would put ~$0.12 of already-spent money into
    # this run's ledger and its reported total.
    payload["cost_event"] = None
    payload["tool_cost_event"] = None
    real_path.write_text(json.dumps(payload, indent=2))

    (PROBE_DIR / f"{ticker}-{arm}.spliced.md").write_text(text)
    return replaced


def restore(ticker: str) -> None:
    backup_path = BACKUP_DIR / f"{ticker}.json"
    if backup_path.exists():
        shutil.move(str(backup_path), str(CACHE_DIR / f"{ticker}.json"))
        print(f"[probe] restored real fundamentals cache for {ticker}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", required=True, choices=["distressed", "exceptional"])
    ap.add_argument("--tickers", nargs="*", default=["MSFT", "ACN"])
    ap.add_argument("--as-of", type=date.fromisoformat, default=AS_OF)
    ap.add_argument("--max-usd", type=float, default=0.75)
    ap.add_argument("--wall-clock-timeout-s", type=float, default=1800.0)
    ap.add_argument(
        "--build-only",
        action="store_true",
        help="Splice and write the variant, then restore. No run, no spend.",
    )
    args = ap.parse_args()

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    for ticker in args.tickers:
        try:
            replaced = swap_in(ticker, args.arm)
            print(f"[probe] {ticker} {args.arm}: replaced {len(replaced)} sections")
            for h in replaced:
                print(f"          {h}")
            if args.build_only:
                continue
            thread_id = f"disc-probe-{ticker.lower()}-{args.arm}-1"
            # Per-arm, so a second arm does not overwrite the first arm's
            # stdout/stderr for the same ticker.
            out_dir = PROBE_DIR / args.arm
            out_dir.mkdir(parents=True, exist_ok=True)
            record = run_one(
                ticker,
                thread_id,
                args.as_of,
                out_dir,
                args.max_usd,
                args.wall_clock_timeout_s,
            )
            records.append(
                {
                    "arm": args.arm,
                    "replaced_sections": replaced,
                    **json.loads(record.model_dump_json()),
                }
            )
        finally:
            restore(ticker)

    if records:
        out = PROBE_DIR / f"results-{args.arm}.json"
        existing = json.loads(out.read_text()) if out.exists() else []
        out.write_text(
            json.dumps(
                existing + [{"recorded_at": datetime.now(timezone.utc).isoformat(),
                             "runs": records}],
                indent=2,
            )
        )
        print(f"\n[probe] results -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
