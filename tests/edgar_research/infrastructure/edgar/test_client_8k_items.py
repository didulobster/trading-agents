"""
list_filings carries each filing's 8-K item numbers from the submissions JSON.

The agent prompt tells the model to read Item 4.01/4.02 off the
check_latest_filings metadata. Before this, list_filings dropped the `items`
array, so an ACN memo on 2026-10-15 reported four 8-Ks as "item numbers not
in the metadata" when SEC's JSON had them all.
"""

import asyncio
from pathlib import Path

from app.edgar_research.infrastructure.edgar.client import EdgarClient


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _client(tmp_path: Path, recent: dict) -> EdgarClient:
    client = EdgarClient(user_agent="test test@example.com", cache_dir=tmp_path)

    async def fake_throttled_get(url: str) -> _FakeResponse:
        return _FakeResponse({"filings": {"recent": recent}})

    client._throttled_get = fake_throttled_get  # bypass real HTTP
    return client


ACN_RECENT = {
    "accessionNumber": ["0001467373-26-000042", "0001467373-26-000032"],
    "form": ["8-K", "10-Q"],
    "filingDate": ["2026-10-14", "2026-06-18"],
    "reportDate": ["2026-10-14", "2026-05-31"],
    "primaryDocument": ["acn-20261014.htm", "acn-20260531.htm"],
    "items": ["7.01,9.01", ""],
}


def test_8k_items_are_split_into_a_list(tmp_path):
    filings = asyncio.run(_client(tmp_path, ACN_RECENT).list_filings("1467373"))

    assert filings[0].items == ["7.01", "9.01"]


def test_a_filing_without_items_gets_an_empty_list(tmp_path):
    filings = asyncio.run(_client(tmp_path, ACN_RECENT).list_filings("1467373"))

    assert filings[1].items == []
