"""The vector sees the filing and section; the stored content does not change."""

import asyncio
from datetime import date

from app.edgar_research.application.reembed import reembed_ticker
from app.edgar_research.domain.chunk import Chunk


def _chunk(cid=1, section_path=("Financial Statements",)) -> Chunk:
    return Chunk(
        id=cid, section_id=1, content="Cash and cash equivalents | 11,478,729 | 5,004,469",
        chunk_index=0, token_count=10, ticker="ACN", filed_date=date(2025, 10, 10),
        filing_type="10-K", section_path=list(section_path),
    )


def test_embedding_text_names_ticker_form_date_and_section_above_the_content():
    assert _chunk().embedding_text() == (
        "ACN 10-K filed 2025-10-10 | Financial Statements\n\n"
        "Cash and cash equivalents | 11,478,729 | 5,004,469"
    )


def test_nested_sections_are_joined():
    text = _chunk(section_path=("Part II", "Item 8")).embedding_text()
    assert text.startswith("ACN 10-K filed 2025-10-10 | Part II > Item 8\n\n")


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


def test_reembed_overwrites_every_vector_from_the_prefixed_text():
    embedder, repo = _Embedder(), _Repo([_chunk(1), _chunk(2)])
    assert asyncio.run(reembed_ticker("ACN", embedder, repo)) == 2
    assert all(t.startswith("ACN 10-K filed") for t in embedder.texts)
    assert repo.updates == [(1, [0.0]), (2, [1.0])]
