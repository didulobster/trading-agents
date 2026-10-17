"""Re-embed a ticker's chunks in place, after the embedding text changes."""

import logging

from app.edgar_research.application.embedding_service import EmbeddingService
from app.edgar_research.infrastructure.repositories.chunk_repo import ChunkRepository

logger = logging.getLogger(__name__)


async def reembed_ticker(ticker: str, embedder: EmbeddingService, chunk_repo: ChunkRepository) -> int:
    """Overwrite every chunk vector for `ticker`; returns how many were written.

    Vectors are replaced, never cleared first, so search keeps working while
    this runs. Old and new vectors are not comparable, so a run interrupted
    half way should simply be repeated.
    """
    chunks = await chunk_repo.list_for_ticker(ticker)
    vectors = await embedder.embed_many([c.embedding_text() for c in chunks])
    await chunk_repo.update_embeddings([(c.id, v) for c, v in zip(chunks, vectors)])
    logger.info("Re-embedded %d chunks for %s", len(chunks), ticker)
    return len(chunks)
