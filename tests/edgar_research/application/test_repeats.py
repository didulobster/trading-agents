"""A footnote restated in every filing collapses to its newest copy."""

from datetime import date

from app.edgar_research.application.repeats import collapse_repeats
from app.edgar_research.domain.chunk import Chunk
from app.edgar_research.infrastructure.repositories.chunk_repo import RetrievedChunk

NOTE_2024 = "Net proceeds from the offerings are being used for general corporate purposes, including repayment of outstanding commercial paper borrowings."
NOTE_2026 = NOTE_2024.replace("borrowings.", "borrowing and funding acquisitions.")
OTHER = "Remaining performance obligations were approximately $37 billion."


def _rc(cid: int, content: str, filed: date, filing_type: str = "10-Q") -> RetrievedChunk:
    chunk = Chunk(
        id=cid, section_id=1, content=content, chunk_index=cid, token_count=1,
        ticker="ACN", filed_date=filed, filing_type=filing_type, section_path=["Part II", "Item 8"],
    )
    return RetrievedChunk(chunk=chunk, similarity=1.0 / cid)


def _ids(results):
    return [r.chunk.id for r in results]


def test_the_newest_copy_takes_the_best_slot_of_its_repeats():
    ranked = [
        _rc(1, NOTE_2024, date(2026, 3, 19)),
        _rc(2, OTHER, date(2026, 10, 16), "10-K"),
        _rc(3, NOTE_2024, date(2026, 6, 18)),
        _rc(4, NOTE_2026, date(2026, 10, 16), "10-K"),
    ]
    assert _ids(collapse_repeats(ranked)) == [4, 2]


def test_an_older_copy_below_a_newer_one_is_dropped():
    ranked = [_rc(1, NOTE_2026, date(2026, 10, 16), "10-K"), _rc(2, NOTE_2024, date(2026, 6, 18))]
    assert _ids(collapse_repeats(ranked)) == [1]


def test_overlapping_chunks_of_one_filing_are_both_kept():
    ranked = [_rc(1, NOTE_2024, date(2026, 6, 18)), _rc(2, NOTE_2024, date(2026, 6, 18))]
    assert _ids(collapse_repeats(ranked)) == [1, 2]


def test_different_text_is_untouched():
    ranked = [_rc(1, NOTE_2024, date(2026, 6, 18)), _rc(2, OTHER, date(2025, 10, 10), "10-K")]
    assert _ids(collapse_repeats(ranked)) == [1, 2]
