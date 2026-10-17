"""How many figures each saved memo could not back, over time. No API calls.

`verify_memo` appends up to three sections to every research, news and
fundamentals memo: Unverified Figures and Quotations, Unbacked Derivations,
and Underived Arithmetic. This reads those sections back out of the vault,
so a rise in unverified literals shows up as a number per week instead of
by reading memos.

    uv run python -m app.edgar_research.scripts.citation_trend [--runs 20] [--ticker ACN]
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_SECTIONS = {
    "## Unverified Figures and Quotations": "unverified",
    "## Unbacked Derivations": "unbacked",
    "## Underived Arithmetic": "underived",
}
_ITEM = re.compile(r"^- \*\*(figure|quote):\*\*")
_KINDS = {"fundamental": "fundamentals", "news": "news", None: "research"}
_NAME = re.compile(r"^(?P<ticker>[A-Z.\-]+?)(?:-(?P<stem>[a-z\-]+?))?(?:-(?P<ts>\d{8}-\d{6}))?\.md$")
_RUN_FOLDER = re.compile(r"^\d{4}-\d{4}-\d{6}$")


def count_flags(memo: str) -> dict[str, int]:
    """Items listed under each verifier section of one memo."""
    counts = dict.fromkeys(_SECTIONS.values(), 0)
    section = None
    for line in memo.splitlines():
        if line.startswith("## "):
            section = _SECTIONS.get(line.strip())
        elif section and _ITEM.match(line):
            counts[section] += 1
    return counts


def memo_run(path: Path) -> tuple[str, str, datetime] | None:
    """(ticker, kind, run time) for a verified memo, else None.

    The time comes from the filename's timestamp or, inside a pipeline run,
    from the run folder's name.
    """
    m = _NAME.match(path.name)
    if not m or path.name.endswith("-provenance.md") or m["stem"] not in _KINDS:
        return None
    if m["ts"]:
        when = datetime.strptime(m["ts"], "%Y%m%d-%H%M%S")
    elif _RUN_FOLDER.match(path.parent.name):
        when = datetime.strptime(path.parent.name, "%Y-%m%d-%H%M%S")
    else:
        return None
    return m["ticker"], _KINDS[m["stem"]], when


def collect(vault: Path, ticker: str | None = None) -> list[tuple[datetime, str, str, dict[str, int]]]:
    rows = []
    for path in vault.rglob("*.md"):
        run = memo_run(path.relative_to(vault))
        if run and (ticker is None or run[0] == ticker.upper()):
            rows.append((run[2], run[0], run[1], count_flags(path.read_text(errors="ignore"))))
    return sorted(rows)


def _print_runs(rows, limit: int) -> None:
    print(f"{'run':<17} {'ticker':<6} {'kind':<13} {'unverified':>10} {'unbacked':>9} {'underived':>10}")
    for when, ticker, kind, c in rows[-limit:]:
        print(f"{when:%Y-%m-%d %H:%M}  {ticker:<6} {kind:<13} {c['unverified']:>10} {c['unbacked']:>9} {c['underived']:>10}")


def _print_weeks(rows) -> None:
    weeks: dict[str, list[dict[str, int]]] = defaultdict(list)
    for when, _, _, c in rows:
        weeks[f"{when:%G-W%V}"].append(c)
    print(f"\n{'week':<9} {'memos':>5} {'unverified/memo':>16} {'memos with any':>15}")
    for week, counts in sorted(weeks.items()):
        unverified = [c["unverified"] for c in counts]
        print(f"{week:<9} {len(counts):>5} {sum(unverified) / len(counts):>16.1f} "
              f"{sum(u > 0 for u in unverified):>10} / {len(counts)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20, help="most recent runs to list")
    parser.add_argument("--ticker")
    args = parser.parse_args()

    from app.shared.config import load_env
    load_env()
    from app.shared.vault import MEMO_DIR

    rows = collect(MEMO_DIR, args.ticker)
    if not rows:
        print(f"No verified memos under {MEMO_DIR}")
        return
    _print_runs(rows, args.runs)
    _print_weeks(rows)


if __name__ == "__main__":
    main()
