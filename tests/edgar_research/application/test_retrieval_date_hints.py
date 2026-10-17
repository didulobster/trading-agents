"""retrieve_hybrid applies a date read from the question, and gives it up if it matches nothing."""

import asyncio
from datetime import date

from app.edgar_research.application.retrieval_service import RetrievalService
from app.edgar_research.infrastructure.repositories.chunk_repo import ChunkSearchFilters


class _Embedder:
    async def embed_many(self, texts):
        return [[0.0] for _ in texts]


class _Repo:
    """Records the filters each vector search sees; every search finds nothing."""

    def __init__(self):
        self.seen: list[ChunkSearchFilters] = []

    async def search_by_embedding(self, query_embedding, k, filters):
        self.seen.append(filters)
        return []

    async def search_by_text(self, query, k, filters):
        return []


def _retrieve(repo, question):
    service = RetrievalService(embedding_service=_Embedder(), chunk_repo=repo)
    return asyncio.run(service.retrieve_hybrid(question, k=8))


def test_the_date_in_the_question_reaches_the_search():
    repo = _Repo()
    _retrieve(repo, "Did Accenture issue notes in July 2026?")
    assert repo.seen[0].filed_after == date(2026, 7, 1)
    assert repo.seen[0].filed_before == date(2026, 7, 31)


def test_a_window_that_matches_nothing_is_retried_without_the_hint():
    repo = _Repo()
    _retrieve(repo, "Did Accenture issue notes in July 2026?")
    assert len(repo.seen) == 2
    assert repo.seen[1] == ChunkSearchFilters()


def test_a_question_without_a_date_searches_once():
    repo = _Repo()
    _retrieve(repo, "Did Accenture raise new debt recently?")
    assert len(repo.seen) == 1
