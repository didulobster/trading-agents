"""check_latest_filings counts as new only filings newer than the corpus.

Found 2026-10-12. ACN's corpus held its 5 newest periodic reports, and the
response said "new_filings_count": 8 — all 8 older than anything ingested.
The prompt says to ingest when new reports are found, so the agent called
ingest_ticker(form_type='10-Q', limit=3), which takes the 3 NEWEST 10-Qs:
already in the corpus, so the call did nothing. 26 of 37 vault ingests
were calls like it.
"""

from app.edgar_research.api import _new_filings


def _f(form: str, filed: str, in_corpus: bool) -> dict:
    return {"form": form, "filing_date": filed, "in_corpus": in_corpus}


def test_older_filings_missing_from_the_corpus_are_not_new():
    filings = [_f("10-Q", "2026-06-18", True), _f("10-K", "2025-10-10", True),
               _f("10-Q", "2025-06-20", False), _f("10-K", "2023-10-12", False)]
    assert _new_filings(filings) == []


def test_a_filing_newer_than_the_corpus_is_new():
    filings = [_f("10-Q", "2026-09-18", False), _f("10-Q", "2026-06-18", True),
               _f("10-Q", "2025-06-20", False)]
    assert _new_filings(filings) == [filings[0]]


def test_on_an_empty_corpus_every_filing_is_new():
    filings = [_f("10-Q", "2026-06-18", False), _f("10-K", "2025-10-10", False)]
    assert _new_filings(filings) == filings
