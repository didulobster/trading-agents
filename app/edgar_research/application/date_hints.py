"""Turn a filing date written in a question into a search filter.

"Did Accenture issue notes after May 31, 2026?" asks about an 8-K, and an 8-K
is found by WHEN it was filed: with no date filter the notes 8-K ranked 9th
behind annual reports (measured on the retrieval gold set), while the same
question worded "in July 2026" ranked 1st.

Only two phrasings are read, because only they name a filing date:
"after/since <Month D, YYYY>" and "in/during <Month YYYY>". Period-end dates
("as of August 31, 2025", "ended May 31, 2026") say nothing about when the
filing was made and are left alone.

A hint can only NARROW the caller's filters. `filed_before` is how a run
keeps out filings after its analysis date, so a hint may never push it later.
"""

import calendar
import re
from dataclasses import replace
from datetime import date

from app.edgar_research.infrastructure.repositories.chunk_repo import ChunkSearchFilters

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTH = "|".join(_MONTHS)

_AFTER = re.compile(
    rf"\b(?:after|since)\s+({_MONTH})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", re.IGNORECASE
)
_IN_MONTH = re.compile(rf"\b(?:in|during)\s+({_MONTH})\s+(\d{{4}})\b", re.IGNORECASE)


def narrow_by_date_hints(question: str, filters: ChunkSearchFilters) -> ChunkSearchFilters:
    """`filters` tightened by any filing date the question states."""
    after, before = filters.filed_after, filters.filed_before

    if match := _AFTER.search(question):
        month, day, year = match.groups()
        after = _later(after, date(int(year), _MONTHS[month.lower()], int(day)))
    elif match := _IN_MONTH.search(question):
        month, year = match.groups()
        first = date(int(year), _MONTHS[month.lower()], 1)
        last = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
        after, before = _later(after, first), _earlier(before, last)

    return replace(filters, filed_after=after, filed_before=before)


def _later(current: date | None, hint: date) -> date:
    return hint if current is None else max(current, hint)


def _earlier(current: date | None, hint: date) -> date:
    return hint if current is None else min(current, hint)
