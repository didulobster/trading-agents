import logging

from app.application.query_decomposer import DecompositionResult, QueryDecomposer
from app.infrastructure.repositories.chunk_repo import (
    ChunkRepository,
    ChunkSearchFilters,
    RetrievedChunk,
)
from .embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class RetrievalService:
    """
    Orchestrates question → embedding → search → ranked chunks.

    Lives at the application layer because it composes multiple infrastructure
    services. Doesn't know about the LLM or how chunks become answers — that's
    the next layer up.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        chunk_repo: ChunkRepository,
        decomposer: QueryDecomposer | None = None
    ):
        self.embedder = embedding_service
        self.chunk_repo = chunk_repo
        self.decomposer = decomposer

    async def retrieve(
        self,
        question: str,
        k: int = 8,
        filters: ChunkSearchFilters | None = None,
    ) -> list[RetrievedChunk]:
        if not question.strip():
            return []

        # Embed the question (single call, batch of 1)
        vectors = await self.embedder.embed_many([question])
        query_vector = vectors[0]
        return await self.retrieve_by_embedding(query_vector, k, filters)


    async def retrieve_by_embedding(
        self,
        query_embedding: list[float],
        k: int = 8,
        filters: ChunkSearchFilters | None = None,
    ) -> list[RetrievedChunk]:
        results = await self.chunk_repo.search_by_embedding(
            query_embedding=query_embedding,
            k=k,
            filters=filters,
        )
        if results:
            top = results[0]
            logger.info(
                "Retrieved %d chunks; top: %s @ %.3f",
                len(results),
                " > ".join(top.chunk.section_path),
                top.similarity,
            )
        else:
            logger.info("Retrieved 0 chunks (filters may be too narrow)")

        return results

    async def retrieve_with_decomposition(
        self,
        question: str,
        k: int = 8,
        filters: ChunkSearchFilters | None = None,
    ) -> tuple[list[RetrievedChunk], DecompositionResult]:
        """
        Retrieve with optional query decomposition.
        Returns (chunks, decomposition_result) so callers can inspect sub-queries.
        """
        if self.decomposer is None:
            # No decomposer configured — fall through to normal retrieval
            chunks = await self.retrieve(question, k=k, filters=filters)
            result = DecompositionResult(
                original_query=question, was_decomposed=False, sub_queries=[question]
            )
            return chunks, result

        decomposition = await self.decomposer.decompose(question)

        if not decomposition.was_decomposed:
            chunks = await self.retrieve(question, k=k, filters=filters)
            return chunks, decomposition

        # Retrieve per sub-query, merge results
        all_chunks: dict[int, RetrievedChunk] = {}  # chunk_id -> best result
        for sub_q in decomposition.sub_queries:
            sub_results = await self.retrieve(sub_q, k=k, filters=filters)
            for chunk in sub_results:
                existing = all_chunks.get(chunk.chunk.id)
                if existing is None or chunk.similarity > existing.similarity:
                    all_chunks[chunk.chunk.id] = chunk

        # Sort merged results by similarity, return top-k
        merged = sorted(all_chunks.values(), key=lambda c: c.similarity, reverse=True)
        merged = merged[:k]

        logger.info(
            "Decomposed retrieval: %d sub-queries -> %d unique chunks -> top %d returned",
            len(decomposition.sub_queries),
            len(all_chunks),
            len(merged),
        )

        return merged, decomposition