"""An ingest with no form type takes the two latest annual reports first.

Found 2026-10-12. With form_type omitted, /ingest took the 3 newest filings
of the whole family, 8-Ks included: ACN got three 8-Ks, ASML three 6-Ks, and
a cold AVGO memo listed every annual-report item as a data gap. Narrowing to
periodic forms alone still gave AVGO and ACN three 10-Qs and no 10-K.

Two, not one: the checklist's risk-factor and MD&A items compare the two
most recent 10-Ks. A live AVGO run with only the FY2025 10-K listed both,
and FY2024 RPO, as data gaps.
"""

import asyncio
from types import SimpleNamespace
from datetime import date

from app.edgar_research.application.ingestion_service import IngestionService
from app.edgar_research.domain.listed_security import ListedSecurity
from app.edgar_research.infrastructure.edgar.models import FilingSummary


def _filing(form: str, filed: str) -> FilingSummary:
    return FilingSummary(accession_number=f"{form}-{filed}", form=form,
                         filing_date=date.fromisoformat(filed), filing_data=None,
                         primary_document="doc.htm", report_date=None)


# ACN's EDGAR list on 2026-10-12, newest first.
ACN = [_filing("8-K", "2026-10-01"), _filing("8-K", "2026-07-10"),
       _filing("8-K", "2026-06-23"), _filing("10-Q", "2026-06-18"),
       _filing("10-Q", "2026-03-19"), _filing("10-Q", "2025-12-18"),
       _filing("10-K", "2025-10-10"), _filing("10-K", "2024-10-03")]
ASML = [_filing("6-K", "2026-07-15"), _filing("6-K", "2026-04-23"),
        _filing("20-F", "2026-02-25"), _filing("20-F", "2025-03-05")]


class _FakeEdgar:
    def __init__(self, family: list[str], filings: list[FilingSummary]):
        self._family, self._filings = family, filings

    async def default_form_types(self, cik):
        return self._family

    async def list_filings(self, cik, form_types=None, since=None):
        return [f for f in self._filings if f.form in form_types]


def _ingested(edgar: _FakeEdgar, **kwargs) -> list[str]:
    service = IngestionService(edgar, None, None, None, None, None, None, None)
    picked = []

    async def upsert_security(ticker):
        return ListedSecurity(id=1, cik="1", ticker=ticker, name=ticker)

    async def upsert_filing(security_id, summary):
        picked.append(summary.accession_number)
        return SimpleNamespace(status=None)

    async def advance(filing, summary, security):
        pass

    service._upsert_security = upsert_security
    service._upsert_filing = upsert_filing
    service._advance_filing = advance
    asyncio.run(service.ingest_security("X", **kwargs))
    return picked


def test_default_takes_the_two_latest_10ks_then_the_newest_10q_not_8ks():
    picked = _ingested(_FakeEdgar(["10-K", "10-Q", "8-K"], ACN), limit=3)
    assert picked == ["10-K-2025-10-10", "10-K-2024-10-03", "10-Q-2026-06-18"]


def test_a_foreign_filer_gets_its_20fs_not_6ks():
    picked = _ingested(_FakeEdgar(["20-F", "6-K"], ASML), limit=3)
    assert picked == ["20-F-2026-02-25", "20-F-2025-03-05"]


def test_limit_one_is_the_annual_report():
    picked = _ingested(_FakeEdgar(["10-K", "10-Q", "8-K"], ACN), limit=1)
    assert picked == ["10-K-2025-10-10"]


def test_an_explicit_form_type_is_taken_as_asked():
    picked = _ingested(_FakeEdgar(["10-K", "10-Q", "8-K"], ACN), form_types=["8-K"], limit=2)
    assert picked == ["8-K-2026-10-01", "8-K-2026-07-10"]
