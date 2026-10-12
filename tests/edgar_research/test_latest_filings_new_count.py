"""check_latest_filings counts as new only filings newer than the corpus.

Found 2026-10-12. ACN's corpus held its 5 newest periodic reports, and the
response said "new_filings_count": 8 — all 8 older than anything ingested.
The prompt says to ingest when new reports are found, so the agent called
ingest_ticker(form_type='10-Q', limit=3), which takes the 3 NEWEST 10-Qs:
already in the corpus, so the call did nothing. 26 of 37 vault ingests
were calls like it.
"""

from app.edgar_research.api import _already_ingested, _new_filings


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


def test_the_latest_annual_report_is_new_when_the_corpus_lacks_it():
    """AVGO, 2026-10-12: a 10-Q and two 8-Ks ingested, nothing newer on
    EDGAR, so the count was 0 and the run went ahead without a 10-K."""
    filings = [_f("10-Q", "2026-09-10", True), _f("10-Q", "2026-06-09", False),
               _f("10-K", "2025-12-18", False), _f("10-K", "2024-12-19", False)]
    assert _new_filings(filings) == [filings[2]]


def test_an_older_annual_report_is_not_new_once_the_latest_is_ingested():
    filings = [_f("10-K", "2025-12-18", True), _f("10-K", "2024-12-19", False)]
    assert _new_filings(filings) == []


def test_a_20f_counts_as_the_annual_report():
    filings = [_f("20-F", "2026-02-25", False), _f("6-K", "2026-07-15", True)]
    assert _new_filings(filings) == [filings[0]]


def test_already_ingested_counts_the_filings_in_the_corpus():
    """It was computed as total minus new, so narrowing "new" reported
    AVGO's 34 listed filings as all ingested."""
    filings = [_f("10-Q", "2026-09-10", True), _f("10-Q", "2026-06-09", False)]
    assert _already_ingested(filings) == 1
