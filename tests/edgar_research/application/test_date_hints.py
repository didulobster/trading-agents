"""A filing date in the question narrows the search; it never widens it."""

from datetime import date

from app.edgar_research.application.date_hints import narrow_by_date_hints
from app.edgar_research.infrastructure.repositories.chunk_repo import ChunkSearchFilters

NONE = ChunkSearchFilters()


def test_after_a_full_date_sets_filed_after():
    got = narrow_by_date_hints("Did Accenture issue senior notes after May 31, 2026?", NONE)
    assert got.filed_after == date(2026, 5, 31) and got.filed_before is None


def test_since_works_like_after():
    got = narrow_by_date_hints("Any new debt since June 1 2026?", NONE)
    assert got.filed_after == date(2026, 6, 1)


def test_in_a_month_sets_that_month_as_the_window():
    got = narrow_by_date_hints("Did Accenture Capital issue notes in July 2026?", NONE)
    assert (got.filed_after, got.filed_before) == (date(2026, 7, 1), date(2026, 7, 31))


def test_leap_february_ends_on_the_29th():
    got = narrow_by_date_hints("What was filed in February 2028?", NONE)
    assert got.filed_before == date(2028, 2, 29)


def test_period_end_dates_are_not_filing_dates():
    for q in (
        "Cash as of August 31, 2025 compared with August 31, 2024",
        "Revenue for the nine months ended May 31, 2026",
        "Debt at November 2, 2025 and November 3, 2024 per the balance sheet",
        "Revenue growth in fiscal 2025 versus fiscal 2024",
    ):
        assert narrow_by_date_hints(q, NONE) == NONE


def test_a_hint_cannot_push_filed_before_past_the_runs_as_of_bound():
    as_of = ChunkSearchFilters(filed_before=date(2026, 7, 15))
    got = narrow_by_date_hints("notes issued in July 2026", as_of)
    assert got.filed_before == date(2026, 7, 15)
    assert got.filed_after == date(2026, 7, 1)


def test_a_hint_cannot_loosen_an_earlier_filed_after():
    got = narrow_by_date_hints("anything after January 5, 2026", ChunkSearchFilters(filed_after=date(2026, 3, 1)))
    assert got.filed_after == date(2026, 3, 1)


def test_other_filters_are_kept():
    base = ChunkSearchFilters(tickers=["ACN"], filing_types=["8-K"])
    got = narrow_by_date_hints("filed in July 2026", base)
    assert got.tickers == ["ACN"] and got.filing_types == ["8-K"]


def test_a_question_without_a_date_is_unchanged():
    assert narrow_by_date_hints("Did Accenture raise new debt recently?", NONE) == NONE
