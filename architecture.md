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
- The /ask grounding prompt permits arithmetic on disclosed figures. The original prompt forbade computing anything ("Do not compute or estimate financial figures"), which caused the system to retrieve both operating income and revenue and then decline to divide them. Simple ratios, margins, and growth rates computed from figures stated in the retrieved context are now allowed; estimation and figures absent from context remain forbidden.

## Limitations

- **Parser assumes explicit "Item N." section headings.** Discovered during dogfooding that some large-cap filers (confirmed: McDonald's) instead use business-friendly headings ("Business Summary", "Management's View of the Business") and rely solely on the SEC table of contents and anchor links to cross-reference Items. The current parser silently produces near-empty section maps on these filings. A future improvement would rebuild parsing around TOC-anchor following, which handles both conventions uniformly.

- **Embedding-only retrieval is literal at a semantic level.** Vector search surfaces chunks lexically near the query, but does not synthesize across passages that discuss the same business concept under different vocabulary. Example: a query about "supply chain risks" on a filer who discusses the topic as "vendor dependencies" or "pharmaceutical procurement" may underperform. Phase 2 will evaluate hybrid search (BM25 + vector) and query expansion against an evaluation harness to measure whether either materially improves recall.

- **Total vocabulary gap between analyst and filer terminology is not bridgeable by current retrieval.** Hybrid search (BM25 + vector) fixes partial-overlap cases (q008 "contingent liabilities" → filer's "commitments and contingencies": S@5 0.0→1.0). But when analyst and filer vocabulary share zero lexical stems (q004 "supply chain risks" → filer's "third-party vendor dependencies"), neither BM25 nor vector search surfaces the relevant chunks. Addressing this would require a curated domain-specific synonym mapping or knowledge graph.

- Multi-year financial tables produce column-misalignment errors. Early eval results suggested table-heavy chunks were unretrievable; that was traced to incorrect gold-set curation, not a retrieval deficiency. But extended dogfooding confirmed a different and real failure mode: retrieval of table chunks works, attribution of figures to fiscal years does not. Annual reports present three-year columns (2023 | 2024 | 2025) with year headers appearing once at the top of the table. When a chunk boundary falls mid-table, the headers sit outside the retrieved window and the model infers column position — sometimes wrongly. Confirmed instances, all on ASML 20-Fs:
  | Reported | Actual | Mechanism |
  |---|---|---|
  | FY2023 FCF €7,167.5M | €3,247.2M | read the 2022 column |
  | FY2025 capex €2.1B | €1,631.2M | read the 2024 column |
  | FY2024 non-current debt €4,631.5M | €3,677.3M | read the 2023 column |
Each was individually plausible and internally consistent. Detection required reconciling against the underlying chunk text by SQL. Partially mitigated by an agent prompt rule requiring the model to state which column maps to which fiscal year before extracting; the rule reduced but did not eliminate occurrences.

- Citation verification is not implemented, and confirmed failures now exist. The system does not programmatically check whether a cited chunk literally contains the claimed text or figures. The originally suspected case (UNH Optum Rx revenue) was disproven — traced to truncated preview display. But Phase 4 agent dogfooding produced three confirmed fabrications that citation verification would have caught:
Invented figure. An ASML memo reported SBC of €345.8M for one fiscal year, cited to extract_metrics, at 1.22% of revenue. The verified series is €134.8M / €172.6M / €202.3M. The figure appears in no chunk and reconciles to nothing; an entire "spike warrants monitoring" narrative was built on it.
Invented textual difference. A memo claimed a contingency disclosure shifted from "reasonably probable" to "reasonably possible" across two filings and flagged it for follow-up. "Reasonably possible" is the standard accounting term; both filings use it.
Invented causation. A memo attributed a debt increase to "new issuance of Eurobonds to fund capex." Debt had in fact declined, because a bond matured.
This moves verification from theoretical safety net to the highest-value unbuilt component. A verifier need only assert that every numeric literal and quoted string in an answer appears in at least one retrieved chunk — cheap to implement, and it catches all three cases above.

- **Known: Incorporation-by-reference filers**
IBM files a shell 10-K where Item 7 (MD&A), Item 7A, and Item 8 
(Financial Statements) each contain only a page-number reference 
to a separate Annual Report to Stockholders exhibit. The current 
pipeline only processes the primary filing document and does not 
follow exhibit references. Financial analysis questions on IBM 
will fail. Other filers using this pattern (common among legacy 
large-caps) will have the same issue.

- **Known: Prolific-filer pagination gap**

SEC's submissions endpoint returns ~40 recent filings in the 
primary response. JPM files ~2,000 forms/month, so only the 
most recent 10-K appears. Older 10-Ks require following 
pagination links to secondary submission files. The current 
EdgarClient.list_filings() does not follow pagination. This 
affects prolific filers (large banks, conglomerates) but not 
typical operating companies. JPM is limited to 1 filing until 
pagination is implemented.

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

Handled in `main.py` via `RetrievalService.retrieve_full()` and `llm.answer_question()`:

1. Validate AskRequest (question, k, optional filters: tickers, filing_types, filed_after/before, section_path_contains).
2. Decomposition check — regex detection for compound-query signals (compar(e|ed|ing), vs, relative to, trajectory, ratio of). Simple queries skip the LLM decomposition call entirely.
3. If compound — LLM decomposes into 2-4 sub-queries in filer vocabulary. If simple — the original question is used as-is.
4. Hybrid retrieval per sub-query — vector search (HNSW over pgvector) and BM25 (ts_rank over the generated tsvector column) run in parallel, merged by reciprocal rank fusion (k=60).
5. Results across sub-queries merged and deduplicated by chunk id, keeping the highest similarity per chunk, truncated to top-k.
6. `citations.format_context_block()` tags each chunk [TICKER FORM YEAR §Item].
7. `llm.answer_question()` calls Claude with a grounding prompt that requires citing every fact, forbids answering from general knowledge, and permits simple arithmetic on figures present in the context.
8. Citation tags present in the answer are extracted by substring match.
9. `AskResponse` bundles answer, cited tags, and source chunks with previews and similarity scores.

**Wiring note.** Both Phase 2 improvements were initially built and measured
against the eval harness but never reached `/ask` — the endpoint continued
calling the vector-only path while `use_hybrid=True` and a `QueryDecomposer`
sat unused on the constructor. The same dead-config pattern existed in
`eval/extract_runner.py`. Neither was caught by tests; both surfaced only
during real usage, when a question that worked in eval failed in the API.
Configuration that is set but not read is invisible to type checkers and to
tests that exercise the same wrong path.

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


## Phase 3: Dogfooding (Real Usage)
 
~15 real investment-research questions across 6 tickers, logged in
`docs/dogfooding-log-phase3-usage.md`. The goal shifted from "find
retrieval bugs" to "does this change how I think about a position."
 
**Finding: value scales with question complexity.**
 
| Question shape | Manual time saved | Worth the tool? |
|---|---|---|
| Single-fact lookup (revenue, segment figure) | none | no |
| Cross-section (Item 1A vs Item 7 on one topic) | 15-20 min | yes |
| Cross-filing (YoY language change) | 20-45 min | yes |
| Cross-company comparison | 20+ min | yes |
| Multi-dimensional synthesis | 45+ min | yes |
 
The system's value proposition is **assembling evidence across documents**,
not answering faster. Single-fact lookups are quicker by opening the filing.
The tool earns its place where an analyst's time goes to finding and
collating rather than interpreting.
 
**Representative verified findings.** AVGO export-control escalation across
three 10-Ks — Huawei named in FY2023 and silently dropped from FY2024/FY2025,
"possible decoupling" upgraded to "the decoupling", supplier-side compliance
risk added in FY2025 (confirmed by SQL: "Huawei" appears in exactly one chunk,
FY2023). ACN bookings-to-revenue divergence with the managed-services
conversion lag identified as mechanism. NFLX content cash-spend vs
amortization gap narrowing from $2.8B to $0.67B.
 
**Recurring analytical pattern.** Across ACN and NFLX independently: risks
disclosed in Item 1A are never connected to results in Item 7 MD&A. ACN
discloses AI automation will "adversely affect the utilization rate of our
professionals" while MD&A attributes margin compression solely to payroll
costs. NFLX's FY2023 content-spend drop is discussed with no reference to
the labor disputes its own Item 1A describes. This disclosure gap is
structural to how 10-Ks are drafted, and surfacing it is one of the
system's more useful outputs.
 
**Bugs found by real usage that tests did not catch:** `/ask` running
vector-only despite both Phase 2 improvements being built; stale sections
in an ingested FIG 10-Q; the grounding prompt forbidding computed ratios;
the decomposition regex missing "Compare X and Y".
 
## Phase 4: Research Agent
 
**Approach: raw Claude tool-use, no framework.** The agent is an HTTP
client of the existing FastAPI server — orchestration only, no new
retrieval logic. `app/agent/{researcher,prompts,tools}.py`.
 
**Loop.** `MAX_TURNS`-bounded conversation; the model plans, calls tools,
reads results, continues until it produces a memo. On budget exhaustion the
loop makes one final call **without** `tools=`, forcing a memo from whatever
was gathered rather than discarding the run.
 
**Tools.** `check_corpus`, `check_latest_filings`, `ingest_ticker`,
`ask_edgar`, `extract_metrics`, `calculate`. Each HTTP branch returns
non-200 responses as an error *string* rather than raising, so a failing
endpoint degrades one checklist item instead of killing the run.
 
**Prompts as behavior specification.** `ANALYST_SYSTEM_PROMPT` encodes a
seven-item research checklist derived from dogfooding (only the items that
retrieved reliably), plus question-phrasing rules learned the hard way:
name the ticker and specific fiscal years in every question, use filer
vocabulary not analyst jargon, never say "last year", name both sections
for cross-section questions, one comparison per question.
 
**Modes.** `researcher TICKER` produces a structured memo. `researcher
--news "headline" TICKER` cross-references a headline against
`watchlist.yaml` (thesis, key metrics, watched risks per ticker) and the
filing corpus, returning a verdict (CONFIRMS / CONTRADICTS / NEUTRAL /
INSUFFICIENT DATA) plus a suggested action.
 
**Output separation.** Tool traces to stderr, memo to stdout, auto-saved to
`docs/memos/{TICKER}-{timestamp}.md`. `2>/dev/null` yields a clean memo.
 
**Validated against manual dogfooding.** On AVGO the agent independently
reproduced 7 of 10 manual findings and surfaced 2 the manual pass missed
(debt/operating-profit deleveraging 5.0x → 2.4x; Caltech patent litigation).
 
### The `calculate` guard
 
The agent was instructed to route all arithmetic through a `calculate`
tool. It did — and produced wrong answers anyway, by passing invented
inputs:
 
```
calculate("(32667.3 - 27.6*1000) / (27.6*1000) * 100")  ->  18.36%
```
 
The base `27.6*1000` is a rounded recollection of a figure the filing
states as 27,558.5, and it is the wrong fiscal year besides. The
calculator returned the correct answer to the wrong question, and the
result carried the apparent authority of a tool call. **A calculator
launders invented inputs into tool-authorized outputs.**
 
Prose rules did not fix this. Four successive rule additions were each
followed procedurally while the error relocated — the rule requiring both
endpoints to be stated was satisfied in prose immediately before an
expression using neither.
 
The fix is structural: `calculate` now requires an `inputs` array declaring
each figure's value, label, fiscal period, and source citation. A validator
rejects any expression containing (a) a numeric literal not declared in
`inputs`, or (b) a unit-conversion multiplier (1000, 1e6, 1e9) — the latter
being a syntactic fingerprint of reconstruction from memory, since a
retrieved figure never needs multiplication to reach its own units.
Rejections return as normal tool results, so the agent reads the reason and
retries within the run.
 
### Known agent limitations
 
- **Fiscal year is inferred from filing year.** Annual reports are filed
  after the period they cover; a 20-F filed February 2026 for a December
  year-end reports FY2025. The agent has labelled figures by filing year,
  producing memos that state the correct value under the wrong fiscal
  period — and, in one run, contradicted itself between sections (the same
  €32,667.3M labelled FY2026 in §1 and FY2025 in §5). Mitigated by a prompt
  rule requiring the fiscal year to be established from the period-end date
  inside the filing.
- **Aggregation errors on component/total figures.** One run reported total
  debt of €6,069.3M, which is exactly €4,374.5M (total) plus €1,694.8M (the
  current portion already inside that total). Both inputs were correctly
  retrieved; the sum was not a valid operation. Mitigated by a prompt rule
  forbidding adding a component to a total that contains it.
- **Causal explanations are unconstrained.** Numeric rules cannot catch
  "the IPO capital raise drove free cash flow" (IPO proceeds are a
  financing activity and cannot affect FCF) or "new Eurobond issuance"
  explaining a debt increase that did not occur. Fabricated causation is
  more persuasive than a bare wrong number because it explains itself.
- **Retrieval is non-deterministic across runs.** Repeated runs against a
  static corpus retrieve different subsets of the available facts. Observed:
  a material OFAC enforcement disclosure present in run 1, absent in runs
  2-3, present in run 4; FY2025 FCF retrieved in three runs and reported
  "data unavailable" in a fourth; revolving-credit-facility terms present,
  absent, then present again. Neither memo in a given pair is uniformly
  better — they fail on different line items. **This, not model capability,
  is currently the binding constraint on memo reliability.**
## Additional Limitations
 
- **Parser changes do not retroactively fix ingested filings.** `_parse`
  skips a document when `sections` rows already exist. Resetting a filing's
  status and deleting its chunks is insufficient — the stale sections
  survive and get re-chunked into the same broken output. A FIG 10-Q
  produced 118 chunks containing only Risk Factors and Legal Proceedings,
  with Item 1 Financial Statements (58K chars) and Item 2 MD&A (45K chars)
  entirely absent, because it had been ingested before a parser fix. Correct
  recovery is: delete `sections` **and** `chunks`, reset status to
  `discovered`, re-run. Result: 167 chunks with the financial statements
  present. `corpus-status` checks chunk *counts*, not section
  *completeness*, so this class of staleness is currently invisible.
- **`ingest` cannot resume a locally-reset filing.** The candidate set comes
  entirely from the live SEC submissions API; the command never
  cross-references local `filings` rows sitting below `EMBEDDED`. Resuming a
  reset filing requires calling `IngestionService._advance_filing()`
  directly with a constructed `FilingSummary`.
- **Foreign private issuers parse but with sparse section labels.** ASML's
  20-F yields usable content (1,591 chunks across three filings) but section
  paths carry Item numbers without titles (`{"Part I", "Item 2"}`), and the
  cover-page basis checkbox produces an artifact section
  (`{Unknown, "Item 17", "☐ Item 18 ☐"}`). Retrieval works; section-targeted
  filtering does not.
- **Some tickers are not ingestable at all.** LVMH (LVMUY) is a Level 1 ADR
  whose parent files with the French AMF, not the SEC. No 10-K, no 20-F, no
  corpus entry possible.
## Cost
 
Per-run token usage is accumulated across the agent loop and logged to
`docs/cost-log.jsonl`. Prompt caching materially changes the cost profile:
an 87% cache-read rate on input reduced one measured research run from
~$0.27 to $0.092, so turn count is a weaker cost lever than expected.
 
**The tracker is incomplete.** It observes only the agent-loop process.
Each `ask_edgar` call triggers further LLM calls server-side (decomposition
plus answer generation, the latter carrying ~8 retrieved chunks as context),
and `extract_metrics` another. With 15-20 `ask_edgar` calls per run,
server-side cost is of the same order as the agent loop. Closing this
requires returning `usage` through `AskResponse` and `FinancialMetrics` and
accumulating it in the same tracker. Embedding costs are not tracked at all.
 
**Model configuration spans three call sites** — the agent loop
(`researcher.AGENT_MODEL`), answer generation (`llm.answer_question`
default), and metric extraction (`extraction_service`). These have
disagreed in practice, which makes both cost attribution and quality
attribution unreliable until they are set deliberately.
 