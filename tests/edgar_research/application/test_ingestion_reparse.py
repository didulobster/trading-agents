"""`reparse_filing` rebuilds a filing from its downloaded document.

Parsing skipped any document that already had sections, so a parser fix
never reached filings ingested before it; and `ingest` couldn't resume a
filing reset by hand because it only walks SEC's live filing list.
"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from app.edgar_research.application.ingestion_service import IngestionService
from app.edgar_research.domain.filing import Filing
from app.edgar_research.domain.values import FilingStatus

ACCESSION = "0001467373-26-000032"


class _FilingRepo:
    def __init__(self, status):
        self.filing = Filing(
            id=7, security_id=1, filing_type="10-Q", filed_date=date(2026, 6, 18),
            accession_number=ACCESSION, status=status,
        )
        self.marked: list[FilingStatus] = []

    async def get_by_accession(self, accession):
        return self.filing if accession == ACCESSION else None

    async def mark_status(self, filing_id, status, error_message=None):
        self.marked.append(status)


class _DocRepo:
    def __init__(self, doc_ids):
        self.doc_ids = doc_ids

    async def list_for_filing(self, filing_id):
        return [SimpleNamespace(id=i) for i in self.doc_ids]


class _SectionRepo:
    def __init__(self):
        self.deleted: list[int] = []

    async def delete_for_document(self, doc_id):
        self.deleted.append(doc_id)
        return 1


class _SecurityRepo:
    async def get_by_id(self, security_id):
        return SimpleNamespace(id=security_id, ticker="ACN")


def _service(status=FilingStatus.EMBEDDED, doc_ids=(3,)):
    filings, sections = _FilingRepo(status), _SectionRepo()
    service = IngestionService(
        edgar_client=None, ticker_resolver=None, embedding_service=None,
        security_repo=_SecurityRepo(), filing_repo=filings,
        document_repo=_DocRepo(list(doc_ids)), section_repo=sections, chunk_repo=None,
    )
    advanced: list = []

    async def fake_advance(filing, summary, security):
        advanced.append((filing.status, summary, security.ticker))

    service._advance_filing = fake_advance
    return service, filings, sections, advanced


def test_deletes_sections_and_walks_forward_from_downloaded():
    service, filings, sections, advanced = _service()

    asyncio.run(service.reparse_filing(ACCESSION))

    assert sections.deleted == [3]
    assert filings.marked == [FilingStatus.DOWNLOADED]
    assert advanced == [(FilingStatus.DOWNLOADED, None, "ACN")]


def test_a_failed_filing_can_be_reparsed():
    service, filings, _, advanced = _service(status=FilingStatus.FAILED)

    asyncio.run(service.reparse_filing(ACCESSION))

    assert advanced[0][0] == FilingStatus.DOWNLOADED


def test_unknown_filing_raises():
    service, *_ = _service()
    with pytest.raises(ValueError, match="No filing"):
        asyncio.run(service.reparse_filing("0000000000-00-000000"))


def test_filing_never_downloaded_points_to_ingest():
    service, _, sections, advanced = _service(doc_ids=())
    with pytest.raises(ValueError, match="run ingest"):
        asyncio.run(service.reparse_filing(ACCESSION))
    assert sections.deleted == [] and advanced == []
