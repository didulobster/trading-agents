"""
Reproduces the reported ASML bug: check_latest_filings/ingest_ticker were
hardcoded to search 10-K/10-Q/8-K only, so a foreign private issuer (which
files 20-F/6-K instead and never files a 10-K) looked like it had zero SEC
filings. The agent then fabricated an incorrect explanation from general
knowledge rather than reporting the actual gap.

IngestionService.ingest_security now auto-detects the filer's form-type
family via EdgarClient.default_form_types when the caller doesn't pin an
explicit form_types list. These tests exercise that branch directly against
a fake EdgarClient, so no real network access or SEC EDGAR calls happen.

No async test plugin is configured in this repo — driven via asyncio.run()
in an ordinary sync test function instead of pytest.mark.asyncio.
"""

import asyncio

from app.application.ingestion_service import IngestionService
from app.domain.listed_security import ListedSecurity


class _FakeEdgar:
    """Records what form_types list_filings was called with; never hits
    the network — default_form_types returns a value fixed at construction."""

    def __init__(self, detected_form_types: list[str]):
        self._detected_form_types = detected_form_types
        self.list_filings_calls: list[list[str] | None] = []

    async def default_form_types(self, cik: str) -> list[str]:
        return self._detected_form_types

    async def list_filings(self, cik, form_types=None, since=None):
        self.list_filings_calls.append(form_types)
        return []


def _service_with_fake_edgar(edgar: _FakeEdgar, cik: str) -> IngestionService:
    service = IngestionService(
        edgar_client=edgar,
        ticker_resolver=None,
        embedding_service=None,
        security_repo=None,
        filing_repo=None,
        document_repo=None,
        section_repo=None,
        chunk_repo=None,
    )

    async def fake_upsert_security(ticker: str) -> ListedSecurity:
        return ListedSecurity(id=1, cik=cik, ticker=ticker, name=ticker)

    service._upsert_security = fake_upsert_security  # bypass real DB/resolver
    return service


def test_omitted_form_types_auto_detects_foreign_private_issuer():
    """Reproduces the ASML case: a foreign private issuer files 20-F/6-K,
    never 10-K. When form_types is omitted, the service must ask
    EdgarClient.default_form_types rather than defaulting to ["10-K"]."""
    edgar = _FakeEdgar(["20-F", "6-K"])
    service = _service_with_fake_edgar(edgar, cik="0000937966")

    asyncio.run(service.ingest_security("ASML", form_types=None, limit=3))

    assert edgar.list_filings_calls == [["20-F", "6-K"]]


def test_omitted_form_types_auto_detects_domestic_filer():
    """A domestic filer must still resolve to the domestic form-type family,
    not silently start including 20-F/6-K."""
    edgar = _FakeEdgar(["10-K", "10-Q", "8-K"])
    service = _service_with_fake_edgar(edgar, cik="0000320193")

    asyncio.run(service.ingest_security("AAPL", form_types=None, limit=3))

    assert edgar.list_filings_calls == [["10-K", "10-Q", "8-K"]]


def test_explicit_form_types_bypasses_auto_detection():
    """An explicit form_types list (e.g. the model asking for '10-Q' only)
    must be used as-is, without calling default_form_types at all."""
    edgar = _FakeEdgar(["20-F", "6-K"])  # would give the wrong answer if used
    service = _service_with_fake_edgar(edgar, cik="0000320193")

    asyncio.run(service.ingest_security("AAPL", form_types=["10-Q"], limit=3))

    assert edgar.list_filings_calls == [["10-Q"]]
