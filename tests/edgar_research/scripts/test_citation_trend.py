from datetime import datetime
from pathlib import Path

from app.edgar_research.scripts.citation_trend import count_flags, memo_run

MEMO = """# ACN memo

## Assessment
Revenue was $69.7 billion.

---

## Unverified Figures and Quotations

The following appear in this memo but were not returned by any tool.

- **figure:** `12.4`
  - context: …a margin of 12.4%…
- **quote:** `we expect strong growth ahead`
  - context: …"we expect strong growth ahead"…

## Unbacked Derivations

- **figure:** `3.1`
  - context: …ratio 3.1x…

## Underived Arithmetic

- **figure:** `67,566`
  - context: …total 67,566…
- **figure:** `1,271`
  - context: …1,271…
"""


def test_counts_each_section():
    assert count_flags(MEMO) == {"unverified": 2, "unbacked": 1, "underived": 2}


def test_clean_memo_counts_zero():
    assert count_flags("# Memo\n\n## Assessment\nAll good.") == {
        "unverified": 0, "unbacked": 0, "underived": 0,
    }


def test_run_from_flat_research_filename():
    run = memo_run(Path("ACN/ACN-20261017-191232.md"))
    assert run == ("ACN", "research", datetime(2026, 10, 17, 19, 12, 32))


def test_run_from_dated_fundamentals_folder():
    run = memo_run(Path("ACN/20261016/2026-1016-101500/ACN-fundamental.md"))
    assert run == ("ACN", "fundamentals", datetime(2026, 10, 16, 10, 15, 0))


def test_run_from_flat_fundamentals_and_news():
    assert memo_run(Path("MSFT/20260823/MSFT-fundamental-20260823-101112.md"))[1] == "fundamentals"
    assert memo_run(Path("AVGO/AVGO-news-20260901-090000.md"))[1] == "news"


def test_unverified_kinds_and_provenance_are_skipped():
    assert memo_run(Path("ACN/20261016/2026-1016-101500/ACN-decision.md")) is None
    assert memo_run(Path("ACN/ACN-20261017-191232-provenance.md")) is None
