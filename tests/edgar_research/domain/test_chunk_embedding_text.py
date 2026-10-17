"""The vector sees the company name; the stored content does not change."""

import asyncio
from datetime import date
from pathlib import Path

from app.edgar_research.application.reembed import reembed_ticker
from app.edgar_research.domain.chunk import Chunk
from app.edgar_research.infrastructure.edgar.ticker_resolver import TickerResolver


def _chunk(cid=1) -> Chunk:
    return Chunk(
        id=cid, section_id=1, content="Cash and cash equivalents | 11,478,729 | 5,004,469",
        chunk_index=0, token_count=10, ticker="ACN", filed_date=date(2025, 10, 10),
        filing_type="10-K", section_path=["Financial Statements"],
    )


def test_embedding_text_puts_the_company_name_above_the_content():
    assert _chunk().embedding_text("Accenture plc") == (
        "Accenture plc\n\nCash and cash equivalents | 11,478,729 | 5,004,469"
    )


def test_the_resolver_reads_the_sec_company_name(tmp_path: Path):
    cache = tmp_path / "company_tickers.json"
    cache.write_text('{"0": {"cik_str": 1467373, "ticker": "ACN", "title": "Accenture plc"}}')
    resolver = TickerResolver("test", cache)
    assert asyncio.run(resolver.company_name("acn")) == "Accenture plc"
    assert asyncio.run(resolver.resolve("ACN")) == "0001467373"
    assert asyncio.run(resolver.company_name("ZZZZ")) is None


class _Embedder:
    def __init__(self):
        self.texts = []

    async def embed_many(self, texts):
        self.texts = texts
        return [[float(i)] for i in range(len(texts))]


class _Repo:
    def __init__(self, chunks):
        self.chunks, self.updates = chunks, None

    async def list_for_ticker(self, ticker):
        return self.chunks

    async def update_embeddings(self, updates):
        self.updates = updates


def test_reembed_overwrites_every_vector_from_the_named_text():
    embedder, repo = _Embedder(), _Repo([_chunk(1), _chunk(2)])
    assert asyncio.run(reembed_ticker("ACN", "Accenture plc", embedder, repo)) == 2
    assert all(t.startswith("Accenture plc\n\n") for t in embedder.texts)
    assert repo.updates == [(1, [0.0]), (2, [1.0])]
