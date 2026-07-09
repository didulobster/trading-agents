# Architecture: edgar-rag-skeleton

## Overview

`edgar-rag-skeleton` is an end-to-end pipeline that ingests SEC EDGAR filings (10-K, 10-Q, 8-K, etc.), parses and chunks them with section-aware structure, embeds them into pgvector, and serves grounded question-answering with citation tracking. Built as a deliberate engineering exercise with attention to ingestion resumability, retrieval performance, and answer trustworthiness.

The codebase follows a clean architecture / DDD-style layering:

- **Domain** — framework-agnostic entities and value objects
- **Application** — orchestration services using domain + infrastructure
- **Infrastructure** — concrete implementations (DB, HTTP clients, parsing, chunking)


## Tech Stack

| Concern | Choice | Why |
|---|---|---|
| API server | FastAPI + Uvicorn | Async-first, native Pydantic integration, lightweight |
| LLM (answer generation) | Anthropic Claude | Strong grounded-reasoning behavior; isolated behind a service for swap-out |
| Embeddings | OpenAI `text-embedding-3-small` | Best-in-class quality/cost; mixed providers were a deliberate choice over single-vendor lock-in |
| Database + vector store | PostgreSQL + pgvector | Single store for relational + vector data — one backup story, one failure surface, joinable with structured metadata for pre-filtered retrieval. Revisit if recall at scale becomes a bottleneck |
| ORM/driver | SQLAlchemy 2.0 + asyncpg / psycopg async pool | Async end-to-end matches the FastAPI runtime |
| Migrations | Alembic | Versioned, reversible migrations from day one — no "how is the schema reproducible?" question for the life of the project |
| HTML parsing | BeautifulSoup4 + lxml (custom parser) | Initially used `edgartools` but encountered breaking API changes between versions and limited control over section boundaries; rebuilt as ~200 lines of focused parsing code with no external library risk |
| Tokenization | tiktoken (cl100k_base) | Matches OpenAI embedding model tokenization for accurate chunk-size budgeting |
| CLI | Typer | Pydantic-like typing for command arguments; same mental model as FastAPI |


## Design Notes

- **Resumable ingestion** via the `Filing` status state machine — reruns pick up at the last completed phase instead of redoing work.
- **Status alone is insufficient to verify data integrity.** A filing can complete the state machine (status = `EMBEDDED`) while producing anomalously little data — e.g., a parser silently failing to detect sections, yielding one chunk where ~100 are expected. The `corpus-status` CLI command cross-checks status against chunk counts and embedded-chunk counts per filing, surfacing silent failures that status alone would mask. This caught the McDonald's parser issue and an earlier ingestion-limit bug during dogfooding; running `corpus-status` is now the first step of every dogfooding session.
- **Denormalized chunk metadata** (`ticker`, `filed_date`, `filing_type`, `section_path` repeated on every chunk row) trades storage for retrieval latency: a query like *"risk-factor chunks from AAPL filed after 2023"* applies the three metadata filters as a cheap bitmap index scan first, then runs the HNSW vector scan over only the filtered subset rather than the entire corpus.
- **TOC deduplication** in the parser (`filing_parser._locate_item_headings`) is a load-bearing detail — without it, sections capture empty table-of-contents entries instead of actual content, since EDGAR filings repeat "Item N" headings in both the TOC and the body.
- **Citation format** (`[TICKER FORM YEAR §Item]`) is human-readable and unambiguous across multi-filing corpora. The current implementation extracts cited tags from the answer by substring match but does not yet verify that each cited chunk *literally contains* the claimed text or numbers. Dogfooding surfaced a real failure case where this matters (see Limitations); per-claim citation verification is Phase 2 work.
- **Aggregate lifecycle vs read-side queries** - Repositories handle aggregate lifecycle (insert, update, find). Cross-aggregate read queries live under infrastructure/queries/ to keep write-side and read-side concerns visibly separate.
- Read-side queries return frozen dataclasses rather than dicts — moves field-name errors from runtime puzzles to static-checker / immediate-crash failures.


## Limitations

- **Parser assumes explicit "Item N." section headings.** Discovered during dogfooding that some large-cap filers (confirmed: McDonald's) instead use business-friendly headings ("Business Summary", "Management's View of the Business") and rely solely on the SEC table of contents and anchor links to cross-reference Items. The current parser silently produces near-empty section maps on these filings. A future improvement would rebuild parsing around TOC-anchor following, which handles both conventions uniformly.

- **Embedding-only retrieval is literal at a semantic level.** Vector search surfaces chunks lexically near the query, but does not synthesize across passages that discuss the same business concept under different vocabulary. Example: a query about "supply chain risks" on a filer who discusses the topic as "vendor dependencies" or "pharmaceutical procurement" may underperform. Phase 2 will evaluate hybrid search (BM25 + vector) and query expansion against an evaluation harness to measure whether either materially improves recall.

- **Total vocabulary gap between analyst and filer terminology is not bridgeable by current retrieval.** Hybrid search (BM25 + vector) fixes partial-overlap cases (q008 "contingent liabilities" → filer's "commitments and contingencies": S@5 0.0→1.0). But when analyst and filer vocabulary share zero lexical stems (q004 "supply chain risks" → filer's "third-party vendor dependencies"), neither BM25 nor vector search surfaces the relevant chunks. Addressing this would require a curated domain-specific synonym mapping or knowledge graph.

- **Numeric retrieval is unreliable on table-heavy filings.** Early eval results suggested table-heavy chunks were unretrievable; this was traced to incorrect gold-set curation rather than a retrieval deficiency. The failure mode is not confirmed.

- **Citation verification is not implemented.** The system does not programmatically check whether each cited chunk literally contains the claimed text or numbers. Dogfooding investigated a suspected citation-precision failure (UNH Optum Rx revenue); the failure was traced to truncated preview display rather than actual misattribution. The risk remains theoretically present and a verification module would add a safety net, but no confirmed failure case currently motivates urgent implementation.


## Domain Model

**Filing state machine** (`domain/values.py`, `domain/filing.py`):

```
DISCOVERED -> DOWNLOADED -> PARSED -> CHUNKED -> EMBEDDED
                   \------------------------------> FAILED (resettable to DISCOVERED)
```

This makes ingestion resumable — each phase only processes filings sitting at the prerequisite status.

**Core entities:**
- `ListedSecurity` — a company (CIK, ticker, exchange, name)
- `Filing` — one filing (type, filed_date, accession_number, status)
- `Document` — pointer to a filing's downloaded HTML (local_path, original_url)
- `Section` — a structural division of a parsed filing (section_path array, content, order)
- `Chunk` — an embeddable unit with denormalized metadata (ticker, filed_date, filing_type, section_path) for fast pre-filtered vector search

## Database Schema

PostgreSQL 16 + pgvector. Five tables mirror the domain entities 1:1, with `chunks` denormalizing parent metadata for retrieval performance:

```
listed_securities (cik UNIQUE, ticker UNIQUE, exchange, name)
        │ 1:N
filings (security_id FK, filing_type, filed_date, accession_number UNIQUE, status enum, error_message)
        │ 1:N
documents (filing_id FK, primary_document_name, original_url, local_path)
        │ 1:N
sections (document_id FK, section_path TEXT[], order, content)
        │ 1:N
chunks (section_id FK, content, chunk_index, token_count, embedding vector(1536),
        ticker, filed_date, filing_type, section_path TEXT[])  -- denormalized for pre-filtering
```

Indexes:
- B-tree on `ticker`, `filed_date`, `filing_type` on `chunks` (cheap pre-filter before vector scan)
- GIN on `section_path` (array containment, e.g. filter by "Risk Factors")
- HNSW on `embedding` with `vector_cosine_ops` (approximate nearest-neighbor search)

Vector search query shape: apply metadata `WHERE` filters first (bitmap index scan), then `ORDER BY embedding <=> query_vector LIMIT k`, with similarity computed as `1 - cosine_distance`.

## Ingestion Pipeline

Orchestrated by `IngestionService` (`application/ingestion_service.py`), driven by the CLI (`ingest` command) per ticker:

1. **Discover** — `TickerResolver` resolves ticker → CIK; `EdgarClient.list_filings()` queries SEC submissions API; filings upserted with status `DISCOVERED`.
2. **Download** — `EdgarClient.download_filing()` fetches and caches HTML under `data/edgar-cache/`; `Document` row created; status → `DOWNLOADED`.
3. **Parse** — `filing_parser.parse_filing()` strips noise (scripts/styles/XBRL), flattens DOM to text blocks, locates `Item N` headings via regex, dedupes table-of-contents repeats (keeps last occurrence), slices into `ParsedSection`s; status → `PARSED`.
4. **Chunk** — `section_chunker.chunk_filing()` splits each section into ~600-token chunks on paragraph boundaries with 80-token overlap between adjacent chunks, never crossing section boundaries, dropping trivial (<50 token) sections; status → `CHUNKED`.
5. **Embed** — `EmbeddingService` batches chunk content through OpenAI embeddings; vectors written back via `ChunkRepository.update_embeddings()`; status → `EMBEDDED`.

SEC EDGAR access is rate-limited client-side (~8 req/sec) and requires a configured `User-Agent`.

## Query Pipeline (`POST /ask`)

Handled in `main.py`, using `RetrievalService` and `llm.answer_question()`:

1. Validate `AskRequest` (question, k, optional filters: tickers, filing_types, filed_after/before, section_path_contains).
2. Embed the question (`EmbeddingService`).
3. `ChunkRepository.search_by_embedding()` — filtered HNSW vector search returns top-k `RetrievedChunk`s with similarity scores.
4. `citations.format_context_block()` builds a context string tagging each chunk as `[TICKER FORM YEAR §Item]`.
5. `llm.answer_question()` calls Claude with a system prompt that requires citing every fact and forbids speculation; returns answer text.
6. Citation tags actually present in the answer are extracted by substring match against expected tags.
7. Response (`AskResponse`) bundles the answer, cited tags, and the source chunks (with previews and similarity scores).

## External Services

| Service | Used for | Auth |
|---|---|---|
| SEC EDGAR (`data.sec.gov`, `www.sec.gov`) | Filing discovery + HTML download | `User-Agent` header (`EDGAR_USER_AGENT`) |
| OpenAI | Embeddings (`text-embedding-3-small`) | `OPENAI_API_KEY` |
| Anthropic | Answer generation (Claude) | `ANTHROPIC_API_KEY` |


## Evaluation
Retrieval quality is measured by an evaluation harness (`eval/`) against a hand-curated test set of 8 questions across 5 categories:
- `numeric_table` (1 question)
- `numeric_prose` (2 questions)
- `narrative_single_section` (1 question)
- `narrative_conceptual_vocabulary` (2 questions)
- `synthesis_multi_component` (2 questions)

For each question, gold chunks are organized by component — single-component for factual questions, multi-component for synthesis questions requiring multiple distinct facts. Metrics per category: success@k (did any gold chunk appear in top-k), coverage@k (fraction of components with ≥1 gold chunk in top-k), recall@k, and MRR.

Baseline (vector-only): overall S@5 = 0.625, with failures concentrated in vocabulary-mismatch (q004, q008) and synthesis (q005, q009) categories.

## Phase 2: Retrieval Improvements
Two retrieval improvements were built and measured against the eval harness, each targeting a distinct failure mode.

### Query Decomposition

**Problem:** Multi-component synthesis questions (q005: "buybacks vs
operational improvement", q009: "debt trajectory relative to operating
profit") returned coverage@5 of 0.25 and 0.0. A single query embedding
dominated by the most salient phrase never explores the semantic
neighborhood of other required components.

**Solution:** Two-stage detection — keyword regex for compound-query signals
("vs", "relative to", "trajectory"), then LLM decomposition into 2-4
sub-queries using filer vocabulary. Simple queries bypass the LLM call
entirely (zero regression risk, zero added cost). The decomposition prompt
instructs the LLM to translate analyst vocabulary to filer terminology —
necessary because the same eval showed "operating income" returns zero rows
for CAT while "operating profit" returns dozens.

**Results:** q005 coverage@5: 0.25 → 0.75. q009 coverage@5: 0.0 → 1.0. No
regression on q001/q002/q003/q006. Does not address single-concept
vocabulary-mismatch questions (q004, q008).

### Hybrid Search (BM25 + Vector)

**Problem:** Single-concept vocabulary-mismatch questions (q008: "contingent
liabilities") failed at S@5 = 0.0 under vector-only retrieval. The filer
uses "commitments and contingencies" — partial lexical overlap that
embeddings miss but keyword matching catches.

**Solution:** Added a `tsvector` column (GENERATED ALWAYS AS stored) to
chunks with a GIN index. BM25 retrieval via `ts_rank` runs in parallel with
vector search. Results merged via reciprocal rank fusion (RRF, k=60).
Deterministic — identical results across runs, unlike LLM-based query
rewriting.

**Results:** q008 S@5: 0.0 → 1.0. No regression on any working question.
q004 remains at 0.0 — total vocabulary gap ("supply chain" shares zero
stems with "third-party vendor"), which neither BM25 nor vector search can
bridge.
