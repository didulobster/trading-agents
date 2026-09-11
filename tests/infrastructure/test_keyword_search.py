"""The keyword half of hybrid retrieval.

`search_by_text` used `plainto_tsquery`, which ANDs every term: a chunk had
to contain every word of the question. On the 2026-09-11 ACN run 40 of 43
hybrid retrievals got zero keyword hits, and 51 of 51 real queries replayed
against the corpus got none — "hybrid" was vector-only. The fix matches ANY
term, ranked by ts_rank (see search_by_text's docstring for the variants
measured against it). These run the real SQL against Postgres, on a
TEMP `chunks` table that shadows the real one for this session only.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date

import pytest

import app.agent.tools as tools
import app.infrastructure.repositories.chunk_repo as chunk_repo
from app.application.retrieval_service import RetrievalService
from app.domain.chunk import Chunk
from app.infrastructure.repositories.chunk_repo import (
    ChunkRepository,
    ChunkSearchFilters,
    RetrievedChunk,
)

DB_URI = os.getenv("TRADING_CHECKPOINT_DB_URI") or os.getenv("POSTGRES_DATABASE_URL")


def _postgres_reachable() -> bool:
    if not DB_URI:
        return False
    try:
        import psycopg

        with psycopg.connect(DB_URI, connect_timeout=2):
            return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(), reason="needs a Postgres at TRADING_CHECKPOINT_DB_URI"
)

CHUNKS = [
    # (ticker, content)
    ("ACN", "Net cash provided by operating activities was $11,474 million, and "
            "purchases of property and equipment were $600 million."),
    ("ACN", "Accenture Accenture Accenture Accenture announced a board appointment."),
    ("ACN", "Revenue grew 7% in local currency."),
    ("MSFT", "Net cash provided by operating activities increased."),
]


@pytest.fixture
async def repo(monkeypatch):
    import psycopg
    from pgvector.psycopg import register_vector_async
    from psycopg.rows import dict_row

    conn = await psycopg.AsyncConnection.connect(DB_URI, row_factory=dict_row, autocommit=True)
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await register_vector_async(conn)
    # Same columns search_by_text reads, and content_tsv defined exactly as
    # migration 25b4b18dcb28 defines it.
    await conn.execute("""
        CREATE TEMP TABLE chunks (
            id serial PRIMARY KEY,
            section_id int NOT NULL DEFAULT 1,
            content text NOT NULL,
            chunk_index int NOT NULL,
            token_count int NOT NULL DEFAULT 10,
            embedding vector(3),
            ticker text NOT NULL,
            filed_date date NOT NULL DEFAULT '2025-10-10',
            filing_type text NOT NULL DEFAULT '10-K',
            section_path text[] NOT NULL DEFAULT ARRAY['Part II', 'Item 7'],
            created_at timestamptz NOT NULL DEFAULT now(),
            content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        )
    """)
    for i, (ticker, content) in enumerate(CHUNKS):
        await conn.execute(
            "INSERT INTO chunks (content, chunk_index, ticker) VALUES (%s, %s, %s)",
            (content, i, ticker),
        )

    @asynccontextmanager
    async def _this_connection():
        yield conn

    monkeypatch.setattr(chunk_repo, "get_connection", _this_connection)
    yield ChunkRepository()
    await conn.close()


@requires_postgres
@pytest.mark.anyio
async def test_a_question_matches_chunks_that_contain_only_some_of_its_words(repo):
    """No chunk contains "plc" or "ACN" — under the old AND semantics this
    question returned nothing at all."""
    rows = await repo.search_by_text(
        "For Accenture plc (ACN), what was net cash provided by operating activities?",
        k=10, filters=ChunkSearchFilters(tickers=["ACN"]),
    )
    assert rows, "the keyword search matched nothing"
    assert rows[0].chunk.chunk_index == 0


@requires_postgres
@pytest.mark.anyio
async def test_a_chunk_covering_the_question_outranks_one_repeating_a_single_word(repo):
    """ts_rank has no inverse document frequency, so the worry with OR is
    that the chunk saying "Accenture" four times wins every question that
    names the company. It does not: matching more of the question's terms
    outweighs repeating one."""
    rows = await repo.search_by_text(
        "Accenture net cash operating activities", k=10,
        filters=ChunkSearchFilters(tickers=["ACN"]),
    )
    order = [r.chunk.chunk_index for r in rows]
    assert order[0] == 0
    assert order.index(0) < order.index(1)


@requires_postgres
@pytest.mark.anyio
async def test_filters_still_apply(repo):
    rows = await repo.search_by_text(
        "net cash provided by operating activities", k=10,
        filters=ChunkSearchFilters(tickers=["MSFT"]),
    )
    assert [r.chunk.ticker for r in rows] == ["MSFT"]


@requires_postgres
@pytest.mark.anyio
async def test_a_query_of_only_stopwords_returns_nothing_rather_than_everything(repo):
    assert await repo.search_by_text("the and of", k=10) == []


# ---------------------------------------------------------------------------
# Fusion keeps the cosine similarity
# ---------------------------------------------------------------------------

def _rc(cid: int, similarity: float, vector_similarity: float | None) -> RetrievedChunk:
    chunk = Chunk(
        id=cid, section_id=1, content="x", chunk_index=cid, token_count=1,
        ticker="ACN", filed_date=date(2025, 10, 10), filing_type="10-K",
        section_path=["Part II", "Item 7"],
    )
    return RetrievedChunk(chunk=chunk, similarity=similarity, vector_similarity=vector_similarity)


def test_fusion_keeps_the_vector_similarity_and_marks_keyword_only_hits():
    vector = [_rc(1, 0.71, 0.71), _rc(2, 0.64, 0.64)]
    keyword = [_rc(2, 5.0, None), _rc(3, 4.0, None)]

    fused = {r.chunk.id: r for r in RetrievalService._reciprocal_rank_fusion(vector, keyword, k=10)}

    assert fused[1].vector_similarity == 0.71
    assert fused[2].vector_similarity == 0.64    # found by both
    assert fused[3].vector_similarity is None    # keyword search only
    assert fused[2].similarity > fused[1].similarity   # RRF rewards agreement


@pytest.mark.anyio
async def test_the_agent_sees_cosine_similarity_not_the_rrf_score(monkeypatch):
    """The fused RRF score read as sim=0.016 on every citation line."""

    class _Resp:
        status_code = 200
        headers: dict = {}
        text = "{}"

        def json(self):
            return {"answer": "a", "chunks": [
                {"citation": "ACN 10-K 2025 §Item 7", "similarity": 0.0325, "vector_similarity": 0.712},
                {"citation": "ACN 10-K 2025 §Item 8", "similarity": 0.0161, "vector_similarity": None},
            ]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, **kw):
            return _Resp()

    monkeypatch.setattr(tools.httpx, "AsyncClient", lambda **kw: _Client())
    monkeypatch.setattr(tools, "USE_STUBS", False)
    tools.reset_run_provenance()

    out = await tools._dispatch("ask_edgar", {"question": "q", "tickers": ["ACN"]})

    assert "[ACN 10-K 2025 §Item 7] sim=0.712" in out
    assert "[ACN 10-K 2025 §Item 8] keyword match" in out
    assert "0.032" not in out and "0.016" not in out


@pytest.fixture
def anyio_backend():
    return "asyncio"
