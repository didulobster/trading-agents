"""EDGAR Research's HTTP endpoints: retrieval, extraction, ingestion and corpus
status. Mounted by app/main.py."""

import asyncio
from dataclasses import asdict
from datetime import date, timedelta
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.shared.api_key import SPENDS_MONEY
from app.shared.config import require_env
from app.shared.llm.models import model_for
from app.shared.ticker import Ticker, normalize_ticker
from app.shared.token_usage import USAGE_HEADER, TokenUsage, encode_usage_header
from app.edgar_research.application.citations import format_citation_tag
from app.edgar_research.application.citation_verifier import verify_answer
from app.edgar_research.application.embedding_service import EmbeddingService
from app.edgar_research.application.extraction_service import FinancialMetrics, MetricsExtractor
from app.edgar_research.application.ingestion_service import IngestionService
from app.edgar_research.application.query_decomposer import QueryDecomposer
from app.edgar_research.application.retrieval_service import RetrievalService, _fuse_across_queries
from app.edgar_research.infrastructure.edgar.client import EdgarClient, periodic_forms
from app.edgar_research.infrastructure.edgar.ticker_resolver import TickerResolver
from app.edgar_research.infrastructure.queries.corpus_status import CorpusStatusQuery
from app.edgar_research.infrastructure.repositories.db import get_connection
from app.edgar_research.infrastructure.repositories.chunk_repo import (
    ChunkRepository,
    ChunkSearchFilters,
)
from app.edgar_research.infrastructure.repositories.document_repo import DocumentRepository
from app.edgar_research.infrastructure.repositories.filing_repo import FilingRepository
from app.edgar_research.infrastructure.repositories.listed_security_repo import ListedSecurityRepository
from app.edgar_research.infrastructure.repositories.section_repo import SectionRepository
from app.edgar_research.application.answer_service import answer_question

router = APIRouter()
claude_model = model_for("answer")


def _embedder(state) -> EmbeddingService:
    """The client the server built at startup (see app/main.py's lifespan),
    or a fresh one when it built none."""
    return getattr(state, "embedder", None) or EmbeddingService()


def _decomposer(state) -> QueryDecomposer:
    return getattr(state, "decomposer", None) or QueryDecomposer()


# ---- Request / response models ----

class AskRequest(BaseModel):
    # A field the server does not understand is a 422, not a shrug. Pydantic's
    # default is to DROP unknown fields, and that is how a 22-hour-stale
    # server accepted `filed_before` on /latest-filings and silently
    # discarded the bound: the caller was told nothing, and a historical run
    # read filings it was not supposed to see. Failing on the first call
    # beats a wrong answer thirty calls later.
    model_config = ConfigDict(extra="forbid")

    question: str
    k: int = 8
    tickers: list[Ticker] | None = None
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
    # Cosine similarity when the vector search found the chunk; None when only
    # the keyword search did. `similarity` is the fused ranking score.
    vector_similarity: float | None = None
    ticker: str
    filing_type: str
    filed_date: date
    content_preview: str


class AskResponse(BaseModel):
    answer: str
    citations: list[str]
    unverified: list[str] = []
    chunks: list[RetrievedChunkResponse]
    dropped_section_filter: list[str] | None = Field(
        default=None,
        description=(
            "Sections that were asked for but match no chunk in this corpus. "
            "When set, the answer was produced WITHOUT the section filter."
        ),
    )

class ExtractRequest(BaseModel):
    # See AskRequest: unknown fields are rejected, not dropped.
    model_config = ConfigDict(extra="forbid")

    ticker: Ticker
    fiscal_period: str          # "Q1 2026" — you supply this, it's not extracted
    filing_type: str            # "10-Q"
    filed_date: date
    filed_after: date | None = None
    filed_before: date | None = None

class IngestRequest(BaseModel):
    # See AskRequest: unknown fields are rejected, not dropped.
    model_config = ConfigDict(extra="forbid")

    ticker: Ticker
    # None = the latest annual report plus the newest quarterlies, from the
    # filer's detected family (10-K/10-Q, or 20-F for a foreign private
    # issuer). Pass explicitly to override, e.g. "8-K" or "6-K".
    form_type: str | None = None
    limit: int = 3
    since_year: int | None = None
    # Re-run filings a previous ingest marked FAILED (they are skipped
    # otherwise). See IngestionService.ingest_security.
    retry_failed: bool = False

class LatestFilingsRequest(BaseModel):
    # See AskRequest: unknown fields are rejected, not dropped.
    model_config = ConfigDict(extra="forbid")

    ticker: Ticker
    # None = auto-detect the filer's form-type family (see IngestRequest).
    form_types: list[str] | None = None
    since_year: int | None = None
    # Upper bound on the filing date. A historical run must not be shown
    # filings published after the date it is analysing — knowing a 10-K
    # exists is itself lookahead, even before anything is read from it.
    filed_before: date | None = None
    # Narrow the auto-detected family to its PERIODIC members (10-K/10-Q, or
    # 20-F), dropping the event-driven ones. Defaults on because a
    # fundamentals checklist is built from periodic reports and the event
    # filings dominate the list by count -- NFLX returned 44 filings of which
    # 38 were 8-Ks, and every one of them then rode in the agent's context
    # for the rest of the run. Ignored when `form_types` is given explicitly:
    # a caller naming its forms has already said what it wants.
    periodic_only: bool = True


# ---- Endpoint ----
def _report_usage(response: Response, *usages: tuple[str, TokenUsage]) -> None:
    """Tell the caller what this request spent, in a header.

    A header and not a body field: the research agent copies tool-result
    bodies verbatim into its provenance corpus, and every numeric guard in
    the trading pipeline does exact containment against that corpus. Four
    token counts added to each retrieval body would be four new numbers that
    could then "back" a figure in a memo. The header leaves the
    agent-visible bytes exactly as they were.

    The caller does the logging, not this server: only it knows the run_id,
    and only its TradingState feeds `check_run_guards`. See
    shared/token_usage.py.

    Each usage is paired with the model that spent it, so the caller can
    price it at that model's rate rather than its own.
    """
    response.headers[USAGE_HEADER] = encode_usage_header(usages)


@router.post("/ask",  response_model=AskResponse, dependencies=SPENDS_MONEY)
async def ask(req: AskRequest, request: Request, response: Response) -> AskResponse:
    if not req.question.strip():
        raise HTTPException(400, "question must not be empty")

    embedder = _embedder(request.app.state)
    chunk_repo = ChunkRepository()
    decomposer = _decomposer(request.app.state)
    retrieval = RetrievalService(
        embedding_service=embedder, 
        chunk_repo=chunk_repo,
        decomposer=decomposer)

    sections = req.section_path_contains
    if sections:
        # An unmatched section name retrieves nothing, and an empty answer
        # reads to the caller as "the filing doesn't say" rather than "you
        # spelled the section wrong". Drop the filter and say so, instead of
        # spending the answer call on no excerpts at all.
        matched = await chunk_repo.sections_with_content(sections, req.tickers)
        if not matched:
            logging.warning(
                "/ask: no chunk is filed under %s; answering without the "
                "section filter", sections,
            )
            sections = None

    filters = ChunkSearchFilters(
        tickers=req.tickers,
        filing_types=req.filing_types,
        filed_after=req.filed_after,
        filed_before=req.filed_before,
        section_path_contains=sections,
    )

    chunks, decomposition = await retrieval.retrieve_full(req.question, k=req.k, filters=filters)
    result = await answer_question(
        question=req.question, 
        chunks=chunks,
        model=claude_model)
    # BOTH calls: the decomposer's rewrite is billed just like the answer.
    _report_usage(
        response, (claude_model, result.usage), (decomposer.model, decomposition.usage)
    )

    report = verify_answer(
        result.answer,
        {c.chunk.id: c.chunk.content for c in chunks},
    )
    logging.info(report.summary())

    return AskResponse(
        answer=result.answer,
        citations=result.citations,
        unverified=[f.value for f in report.unverified], 
        chunks=[
            RetrievedChunkResponse(
                citation=format_citation_tag(c),
                section_path=c.chunk.section_path,
                similarity=c.similarity,
                vector_similarity=c.vector_similarity,
                ticker=c.chunk.ticker,
                filing_type=c.chunk.filing_type,
                filed_date=c.chunk.filed_date,
                content_preview=c.chunk.content[:300] + ("…" if len(c.chunk.content) > 300 else ""),
            )
            for c in chunks
        ],
        dropped_section_filter=(
            req.section_path_contains if sections is None and req.section_path_contains
            else None
        ),
    )


@router.post("/extract", response_model=FinancialMetrics, dependencies=SPENDS_MONEY)
async def extract(req: ExtractRequest, request: Request, response: Response) -> FinancialMetrics:
    embedder = _embedder(request.app.state)
    chunk_repo = ChunkRepository()
    decomposer = _decomposer(request.app.state)
    retrieval = RetrievalService(
        embedding_service=embedder, 
        chunk_repo=chunk_repo,
        decomposer=decomposer)
    extractor = MetricsExtractor()

    # The window defaults to filed_date ± 30 days; a caller that names its
    # own bounds gets them. The extract_metrics tool has always offered
    # filed_after/filed_before to the agent, and they used to be ignored
    # here, so the agent was steering with a control connected to nothing.
    window_start = req.filed_after or req.filed_date - timedelta(days=30)
    window_end = req.filed_before or req.filed_date + timedelta(days=30)
    if window_start > window_end:
        raise HTTPException(
            400, f"filed_after {window_start} is later than filed_before {window_end}"
        )
    chunks = await gather_extraction_chunks(retrieval, req.ticker, window_start, window_end)
    extracted = await extractor.extract(chunks, req.ticker, req.fiscal_period, req.filing_type, req.filed_date)
    # Only the extraction call spends here: gather_extraction_chunks runs
    # fixed queries through retrieve_hybrid, which never calls the decomposer.
    _report_usage(response, (extractor.llm_model, extractor.last_usage))
    return extracted

async def gather_extraction_chunks(retrieval: RetrievalService, ticker: str, filed_after, filed_before):
    """The four fixed metric queries, fused into one list.

    Concurrent rather than one at a time, and fused by SUMMING each chunk's
    RRF score across the queries that found it rather than keeping the max —
    both for the reasons `_fuse_across_queries` gives. A chunk the cash-flow
    and income-statement queries both surface is more likely to be the
    statements page than one only a single query reached.
    """
    filters = ChunkSearchFilters(tickers=[ticker], filed_after=filed_after, filed_before=filed_before)
    per_query = await asyncio.gather(*(
        retrieval.retrieve_hybrid(query, k=5, filters=filters)
        for query in RetrievalService.METRIC_QUERIES.values()
    ))
    # No top-k truncation here: the extractor wants every distinct chunk the
    # four queries found, ordered by how much of the set agreed on it.
    return _fuse_across_queries(per_query, k=sum(len(r) for r in per_query))


@router.get("/corpus-status")
async def corpus_status_endpoint(ticker: str | None = None, filed_before: date | None = None):
    """`filed_before` bounds every section at the caller's analysis date.

    A historical run could not READ a later filing but could still SEE it:
    a live FIG run at --as-of 2026-03-01 listed two post-cutoff 10-Qs by
    date in its own memo. Knowing a filing exists, and when, is information
    from after the cutoff.
    """
    if ticker is not None:
        try:
            ticker = normalize_ticker(ticker)
        except ValueError as e:
            raise HTTPException(422, str(e))
    query = CorpusStatusQuery()
    summary = await query.summary(ticker, filed_before)
    if not summary:
        return {"summary": [], "issues": [], "per_filing": []}

    issues = await query.issues(ticker, filed_before)
    per_filing = await query.per_filing(ticker, filed_before)

    return {
        "summary": [asdict(row) for row in summary],
        "issues": [asdict(i) for i in issues],
        "per_filing": [asdict(d) for d in per_filing],
        # What `ask_edgar`'s `sections` filter will actually match. Without
        # this the agent guesses note titles, and the filter is dropped.
        "sections_available": await query.item_sections(ticker, filed_before),
    }

@router.post("/ingest", dependencies=SPENDS_MONEY)
async def ingest_endpoint(req: IngestRequest, request: Request):
    user_agent = require_env("EDGAR_USER_AGENT")
    cache_root = Path(os.environ.get("EDGAR_CACHE_DIR", "./data/edgar-cache"))

    async with EdgarClient(user_agent, cache_root / "filings") as edgar:
        resolver = TickerResolver(user_agent, cache_root / "company_tickers.json")
        embedder = _embedder(request.app.state)
        service = IngestionService(
            edgar_client=edgar,
            ticker_resolver=resolver,
            embedding_service=embedder,
            security_repo=ListedSecurityRepository(),
            filing_repo=FilingRepository(),
            document_repo=DocumentRepository(),
            section_repo=SectionRepository(),
            chunk_repo=ChunkRepository(),
        )
        since = date(req.since_year, 1, 1) if req.since_year else None
        await service.ingest_security(
            ticker=req.ticker,
            form_types=[req.form_type] if req.form_type else None,
            limit=req.limit,
            since=since,
            retry_failed=req.retry_failed,
        )

    return {"status": "ok", "ticker": req.ticker, "limit": req.limit}


def _new_filings(filings: list[dict]) -> list[dict]:
    """Filings filed after the newest one already in the corpus.

    Older filings missing from the corpus are not new: counting them told
    the agent to ingest, and ingest_ticker takes the newest filings, which
    were already there.
    """
    ingested = [f["filing_date"] for f in filings if f["in_corpus"]]
    newest = max(ingested, default="")
    return [f for f in filings if not f["in_corpus"] and f["filing_date"] > newest]


@router.post("/latest-filings")
async def latest_filings_endpoint(req: LatestFilingsRequest):
    user_agent = require_env("EDGAR_USER_AGENT")
    cache_root = Path(os.environ.get("EDGAR_CACHE_DIR", "./data/edgar-cache"))

    async with EdgarClient(user_agent, cache_root / "filings") as edgar:
        resolver = TickerResolver(user_agent, cache_root / "company_tickers.json")
        cik = await resolver.resolve(req.ticker)
        if not cik:
            raise HTTPException(404, f"Could not resolve ticker {req.ticker}")

        form_types = req.form_types
        if form_types is None:
            form_types = await edgar.default_form_types(cik)
            if req.periodic_only:
                form_types = periodic_forms(form_types)

        since = date(req.since_year, 1, 1) if req.since_year else None
        sec_filings = await edgar.list_filings(
            cik=cik, form_types=form_types, since=since,
        )

    if req.filed_before:
        sec_filings = [f for f in sec_filings if f.filing_date <= req.filed_before]

    accession_numbers = [f.accession_number for f in sec_filings]
    ingested: dict[str, str] = {}
    if accession_numbers:
        async with get_connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT f.accession_number, f.status::text AS status
                FROM filings f
                JOIN listed_securities s ON s.id = f.security_id
                WHERE s.ticker = %s AND f.accession_number = ANY(%s)
                """,
                (req.ticker, accession_numbers),
            )
            rows = await cur.fetchall()
            ingested = {r["accession_number"]: r["status"] for r in rows}

    filings_list = []
    for f in sec_filings:
        status = ingested.get(f.accession_number)
        filings_list.append({
            "accession_number": f.accession_number,
            "form": f.form,
            "filing_date": f.filing_date.isoformat(),
            "report_date": f.report_date.isoformat() if f.report_date else None,
            "in_corpus": status is not None,
            "corpus_status": status,
        })

    new_filings = _new_filings(filings_list)
    return {
        "ticker": req.ticker,
        "form_types_searched": form_types,
        # Echoed so a reader of the agent's trace can see the run was bounded.
        "filed_before": req.filed_before.isoformat() if req.filed_before else None,
        "total_on_sec": len(filings_list),
        "already_ingested": len(filings_list) - len(new_filings),
        "new_filings_count": len(new_filings),
        "filings": filings_list,
    }

