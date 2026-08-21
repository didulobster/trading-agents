"""
EdgarClient.default_form_types picks the filer's form-type family (domestic
10-K/10-Q/8-K vs. foreign private issuer 20-F/6-K) from filing history, so
callers that omit form_types don't silently search only domestic forms
against a company like ASML that never files a 10-K.

No real network access: _throttled_get is monkeypatched to return a fake
submissions-JSON response. No async test plugin is configured in this repo,
so the coroutine is driven via asyncio.run() rather than pytest.mark.asyncio.
"""

import asyncio
from pathlib import Path

from app.infrastructure.edgar.client import (
    DOMESTIC_FORM_TYPES,
    FOREIGN_PRIVATE_ISSUER_FORM_TYPES,
    EdgarClient,
)


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _client(tmp_path: Path, recent_forms: list[str]) -> EdgarClient:
    client = EdgarClient(user_agent="test test@example.com", cache_dir=tmp_path)

    async def fake_throttled_get(url: str) -> _FakeResponse:
        return _FakeResponse({"filings": {"recent": {"form": recent_forms}}})

    client._throttled_get = fake_throttled_get  # bypass real HTTP
    return client


def test_20f_in_filing_history_selects_foreign_private_issuer_forms(tmp_path):
    client = _client(tmp_path, recent_forms=["20-F", "6-K", "6-K", "SC 13G"])

    result = asyncio.run(client.default_form_types("0000937966"))

    assert result == FOREIGN_PRIVATE_ISSUER_FORM_TYPES


def test_no_20f_in_filing_history_selects_domestic_forms(tmp_path):
    client = _client(tmp_path, recent_forms=["10-K", "10-Q", "8-K", "S-8"])

    result = asyncio.run(client.default_form_types("0000320193"))

    assert result == DOMESTIC_FORM_TYPES


def test_empty_filing_history_defaults_to_domestic_forms(tmp_path):
    """A brand-new or unresolved filer with no recent forms yet should not
    be assumed foreign — domestic is the safer, more common default."""
    client = _client(tmp_path, recent_forms=[])

    result = asyncio.run(client.default_form_types("0000000000"))

    assert result == DOMESTIC_FORM_TYPES
