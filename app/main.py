from typing import Literal
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from datetime import date
from fastapi.middleware.cors import CORSMiddleware

from app.application.embedding_service import EmbeddingService
from app.application.extraction_service import FinancialMetrics
from app.application.query_decomposer import QueryDecomposer
from app.application.retrieval_service import RetrievalService
from app.infrastructure.repositories.db import init_pool, close_pool
from app.infrastructure.repositories.chunk_repo import (
    ChunkRepository,
    ChunkSearchFilters,
)
from app.llm import answer_question


app = FastAPI(title="RAG Skeleton")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your actual origin once you know it
    allow_methods=["POST"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_pool()

@app.on_event("shutdown")
async def _shutdown() -> None:
    await close_pool()

# ---- Request / response models ----

class AskRequest(BaseModel):
    question: str
    k: int = 8
    tickers: list[str] | None = None
    filing_types: list[str] | None = None
    filed_after: date | None = None
    filed_before: date | None = None
    section_path_contains: list[str] | None = Field(
        default=None,
        description="e.g. ['Risk Factors'] to restrict to Item 1A sections",
    )

class RetrievedChunkResponse(BaseModel):
    citation: str
    section_path: list[str]
    similarity: float
    ticker: str
    filing_type: str
    filed_date: date
    content_preview: str


class AskResponse(BaseModel):
    answer: str
    citations: list[str]
    chunks: list[RetrievedChunkResponse]

class ExtractRequest(BaseModel):
    ticker: str
    fiscal_period: str          # "Q1 2026" — you supply this, it's not extracted
    filing_type: str            # "10-Q"
    filed_date: date
    filed_after: date | None = None
    filed_before: date | None = None

class FinancialMetricsResponse(BaseModel):
    ticker: str
    fiscal_period: str
    metrics: FinancialMetrics   # the Pydantic model from point 2
    citations: list[str]

# ---- Endpoint ----
@app.post("/ask",  response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    if not req.question.strip():
        raise HTTPException(400, "question must not be empty")

    embedder = EmbeddingService()
    chunk_repo = ChunkRepository()
    decomposer = QueryDecomposer()
    retrieval = RetrievalService(
        embedding_service=embedder, 
        chunk_repo=chunk_repo,
        decomposer=decomposer,
        use_hybrid=True)

    filters = ChunkSearchFilters(
        tickers=req.tickers,
        filing_types=req.filing_types,
        filed_after=req.filed_after,
        filed_before=req.filed_before,
        section_path_contains=req.section_path_contains,
    )

    chunks = await retrieval.retrieve(req.question, k=req.k, filters=filters)
    result = await answer_question(req.question, chunks)

    from app.application.citations import format_citation_tag
    return AskResponse(
        answer=result.answer,
        citations=result.citations,
        chunks=[
            RetrievedChunkResponse(
                citation=format_citation_tag(c),
                section_path=c.chunk.section_path,
                similarity=c.similarity,
                ticker=c.chunk.ticker,
                filing_type=c.chunk.filing_type,
                filed_date=c.chunk.filed_date,
                content_preview=c.chunk.content[:300] + ("…" if len(c.chunk.content) > 300 else ""),
            )
            for c in chunks
        ],
    )


@app.post("/extract", response_model=FinancialMetrics)
async def extract(req: ExtractRequest) -> FinancialMetrics:
    chunks = await gather_extraction_chunks(retrieval, req.ticker, req.filed_after, req.filed_before)
    metrics = await extractor.extract(chunks, req.ticker, req.fiscal_period)
    await metrics_repo.upsert(ticker=req.ticker, period=req.fiscal_period, filing_type=req.filing_type,
                                filed_date=req.filed_date, metrics=metrics,
                                citations=[format_citation_tag(c) for c in chunks])
    return metrics

    async def gather_extraction_chunks(retrieval: RetrievalService, ticker: str, filed_after, filed_before):
        filters = ChunkSearchFilters(tickers=[ticker], filed_after=filed_after, filed_before=filed_before)
        chunks = []
        for query in METRIC_QUERIES.values():
            chunks += await retrieval.retrieve(query, k=5, filters=filters)
        return dedupe_by_chunk_id(chunks)