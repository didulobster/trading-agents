---
last_mapped_commit: 8a7c506660f3af4394b728e0ea36e9b78d2baeb2
last_mapped_at: 2026-09-27
---
<!-- refreshed: 2026-09-27 -->

# Architecture

**Analysis Date:** 2026-09-27

## System Overview

Two systems share one repository and meet at one point. The **EDGAR RAG pipeline** is everything under `app/` outside `app/agent/trading/`. The **multi-agent trading pipeline** is `app/agent/trading/`. The meeting point is the Fundamentals Analyst (`app/agent/trading/infrastructure/fundamentals_port.py`). It wraps the EDGAR research agent (`app/agent/researcher.py::run_agent`), and that agent reaches the RAG API over HTTP at `http://localhost:8000` (`app/agent/tools.py`, `API_BASE`).

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                           ENTRY POINTS                                    │
├───────────────────┬───────────────────┬──────────────────┬───────────────┤
│ FastAPI server    │ RAG CLI (Typer)   │ Research agent   │ Trading CLI   │
│ `app/main.py`     │ `app/cli.py`      │ `app/agent/      │ `app/agent/   │
│                   │                   │  researcher.py`  │  trading/     │
│                   │                   │                  │  interface/   │
│                   │                   │                  │  cli.py`      │
└────────┬──────────┴────────┬──────────┴────────┬─────────┴──────┬────────┘
         │                   │     HTTP :8000 ▲  │ tools.py       │
         ▼                   ▼                │  ▼                ▼
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│ RAG application services         │   │ Trading LangGraph                │
│ `app/application/`               │   │ `app/agent/trading/infrastructure│
│ ingestion, retrieval, embedding, │   │  /graph.py`                      │
│ extraction, citation verifier    │   │ analysts → debate → risk →       │
└────────┬─────────────────────────┘   │ synthesizer (+ graceful_abort)   │
         │                             └────────┬─────────────────────────┘
         ▼                                      ▼
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│ RAG infrastructure               │   │ Trading ports                    │
│ `app/infrastructure/`            │   │ `app/agent/trading/infrastructure│
│ edgar, parsing, chunking,        │   │  /*_port.py`                     │
│ repositories, queries, llm       │   │ LLM, yfinance, Finnhub, disk     │
└────────┬─────────────────────────┘   └────────┬─────────────────────────┘
         ▼                                      ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Postgres 16 + pgvector (chunks, filings, metrics; LangGraph checkpoints) │
│ Vault on disk (`MEMO_DIR`), cost log `docs/cost-log*.jsonl`              │
└──────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| HTTP API | `/ask`, `/extract`, `/ingest`, `/latest-filings`, `/corpus-status`, `/news-assess`, `/trading/analyze`, `/health` | `app/main.py` |
| RAG CLI | ingest, corpus-status, eval, extract-metrics, inspect-chunks | `app/cli.py` |
| Env loading | `load_env()` loads `.env` without overriding values already set; `require_env()` raises `MissingSetting` | `app/config.py` |
| Answer generation | Grounded answer prompt plus the `/ask` LLM call | `app/llm.py` |
| Ingestion | discover → download → parse → chunk → embed, resumable through the Filing status machine | `app/application/ingestion_service.py` |
| Retrieval | Hybrid BM25 + vector search with multi-query fusion | `app/application/retrieval_service.py` |
| Citation verification | Checks numbers and quotes in an answer against the retrieved chunks | `app/application/citation_verifier.py`, `app/application/number_matching.py` |
| Memo verification | Checks memo figures and checks the verdict for consistency | `app/application/memo_verifier.py`, `app/application/verdict_consistency.py` |
| LLM routing | Picks the provider from the model-id prefix; falls back when a model rejects temperature | `app/infrastructure/llm/client.py`, `app/infrastructure/llm/openai_compat.py` |
| Model roles / pricing | Maps role to env var to model id; holds the token pricing table | `app/infrastructure/llm/models.py`, `app/infrastructure/llm/pricing.py` |
| Research agent | Tool-use loop with a turn cap, prompt caching and cost logging | `app/agent/researcher.py`, `app/agent/tools.py`, `app/agent/prompts.py` |
| Trading graph | Wires the LangGraph nodes, cycles, guarded edges and abort path | `app/agent/trading/infrastructure/graph.py` |
| Run lifecycle | Chooses between start, resume and replay; refuses stale budgets; writes vault artifacts | `app/agent/trading/interface/runner.py` |
| Checkpointing | Postgres saver with a custom serde | `app/agent/trading/infrastructure/checkpointer.py` |

## Pattern Overview

**Overall:** Layered clean architecture in DDD style (domain / application / infrastructure / interface). The trading package repeats the same layering inside itself, and a LangGraph state machine orchestrates it.

**Key Characteristics:**
- **The model writes prose and Python owns the facts.** Python assigns identifiers, counters and labels; values arriving from the model are never trusted for these. Every figure in a debate turn must appear verbatim in the evidence pack (`app/agent/trading/infrastructure/debate_port.py`).
- **Structured LLM output goes through one helper.** It uses forced tool calls validated against a Pydantic schema, retries on schema errors, and crashes hard on unrecoverable output (`app/agent/trading/infrastructure/structured_call.py::call_with_schema_retry`, `force_crash`).
- **Termination is guaranteed in three independent ways.** The pure routers enforce caps (`debate_router.py`, `risk_router.py`), the runner derives a `recursion_limit` (`interface/runner.py`), and nodes assert at entry.
- **Point-in-time bounding.** `as_of_date` is set once at the CLI boundary. Nodes never call `date.today()`, and tools send `filed_before`.
- **Degradation is explicit.** Analyst failures go into `analyst_failures`, each stage adds its blind spots to the memo's `data_gaps`, and budget breaches route to `graceful_abort`.

## Layers

**RAG Domain:**
- Purpose: Entities and value objects: Filing, Document, Section, Chunk, ListedSecurity, Ticker, TokenUsage
- Location: `app/domain/`
- Contains: Dataclasses/Pydantic types and pure helpers such as `normalize_ticker`
- Depends on: nothing inside the app
- Used by: every other layer

**RAG Application:**
- Purpose: Orchestration services
- Location: `app/application/`
- Contains: `IngestionService`, `RetrievalService`, `EmbeddingService`, `MetricsExtractor`, `QueryDecomposer`, the verifiers
- Depends on: `app/domain/`, `app/infrastructure/` (repositories, llm, edgar)
- Used by: `app/main.py`, `app/cli.py`, `eval/`

**RAG Infrastructure:**
- Purpose: DB, HTTP, parsing, chunking, LLM clients
- Location: `app/infrastructure/`
- Contains: `edgar/` (SEC client, ticker resolver), `parsing/filing_parser.py`, `chunking/section_chunker.py`, `repositories/*_repo.py` (write-side aggregates), `queries/corpus_status.py` (read-side queries that return frozen dataclasses), `llm/`
- Depends on: `app/domain/`
- Used by: the application services and entry points

**Trading Domain:**
- Purpose: Pure Pydantic types and rules, with no network, LLM or clock access
- Location: `app/agent/trading/domain/`
- Contains: `trading_state.py` (`TradingState` TypedDict), `decision_memo.py`, `debate.py`, `risk.py`, `budget.py` (`RunBudget`, `CostEvent`, `NodeBudgetExceeded`), `sanitize.py`, `validation.py`, `errors.py`
- Depends on: stdlib and Pydantic
- Used by: every trading layer

**Trading Application:**
- Purpose: Graph nodes, routers, deterministic computation
- Location: `app/agent/trading/application/`
- Contains: `nodes.py` (analyst, synthesizer and abort nodes, plus caveat computation), `debate_nodes.py`, `risk_nodes.py`, `debate_router.py`/`risk_router.py` (pure routing functions), `guards.py` (`check_run_guards`), `risk_ledger.py`, `technical_indicators.py`
- Depends on: trading domain and trading infrastructure ports (nodes import the ports directly)
- Used by: `infrastructure/graph.py`

**Trading Infrastructure (ports):**
- Purpose: Talks to LLMs, vendors and disk
- Location: `app/agent/trading/infrastructure/`
- Contains: `*_port.py` (fundamentals, price_data, news_data, news_digest, technical_interpreter, debate, risk, synthesis, decision_memo), `structured_call.py`, `cost_log.py`, `run_log.py`, `checkpointer.py`, `graph.py`
- Depends on: trading domain, `app/infrastructure/llm`, `app/agent/researcher.py`
- Used by: the application nodes and the interface

**Trading Interface:**
- Purpose: Process entry and run lifecycle
- Location: `app/agent/trading/interface/`
- Contains: `cli.py` (argparse main), `runner.py` (`start_or_resume`, `initial_state`, `save_vault_artifacts`)
- Used by: the command line and `app/main.py` (`POST /trading/analyze`)

## Data Flow

### Trading Run

1. The CLI parses the ticker, `--as-of`, `--only` and `--max-usd`, and captures the terminal log (`app/agent/trading/interface/cli.py:33` `run`, `infrastructure/run_log.py::capture_terminal_log`)
2. It builds the checkpointer and the graph (`infrastructure/checkpointer.py:84`, `infrastructure/graph.py::build_trading_graph`)
3. `start_or_resume` replays a completed thread, resumes an unfinished one after checking the budget is not stale, or starts one from `initial_state` (`interface/runner.py:159`)
4. Analysts run in `ANALYST_CHAINS` order: `fundamentals` → `technical` → `news` → `sentiment` (`application/nodes.py:103,138,196,251`)
5. The debate cycle alternates `bull_turn` and `bear_turn` under `next_debate_step`, then passes through `debate_close` (`application/debate_nodes.py`, `debate_router.py`)
6. The risk cycle rotates `neutral_turn` → `aggressive_turn` → `conservative_turn` under `next_risk_step`, then passes through `risk_close` (`application/risk_nodes.py`, `risk_router.py`)
7. `synthesizer_node` runs the research manager and the risk judge, samples several times, takes a majority vote, verifies the memo, and builds `DecisionMemo` (`application/nodes.py:676`, `infrastructure/synthesis_port.py`)
8. The runner writes the run summary to the cost log and saves the memo and run log to the vault (`interface/runner.py:212,234`, `infrastructure/cost_log.py::log_run_summary`)

Every edge after START is wrapped by `_guarded()` in `graph.py`. When a budget, deadline or node-budget breach is detected, the edge routes to `graceful_abort`.

### Fundamentals (Seam) Path

1. `fundamentals_node` calls `get_fundamentals_report(ticker, as_of, ...)` (`infrastructure/fundamentals_port.py:92`)
2. That calls `run_agent(task, ANALYST_SYSTEM_PROMPT, stop_check=budget_stop_check(...), as_of=as_of)` (`app/agent/researcher.py:549`)
3. The agent's tools (`app/agent/tools.py`) send HTTP requests to `app/main.py` endpoints (`/ask`, `/latest-filings`, `/ingest`) with `filed_before=as_of`
4. The result is a `FundamentalsReport` Pydantic model

### RAG `/ask` Path

1. `POST /ask` (`app/main.py:272`, protected by `SPENDS_MONEY` = `require_api_key` using `APP_API_KEY`)
2. `QueryDecomposer` splits the question into sub-queries (`app/application/query_decomposer.py`)
3. `RetrievalService` runs hybrid search per sub-query, then fuses the results with `_fuse_across_queries` (`app/application/retrieval_service.py:16,53`) over `ChunkRepository` (`app/infrastructure/repositories/chunk_repo.py`)
4. `app/llm.py` generates the cited answer, and `verify_answer` checks it (`app/application/citation_verifier.py`)

### Ingestion Path

1. `app.cli ingest` or `POST /ingest` → `IngestionService` (`app/application/ingestion_service.py:30`)
2. `EdgarClient` downloads the filing (`app/infrastructure/edgar/client.py`) → `filing_parser` extracts sections → `section_chunker` produces chunks → `EmbeddingService` (OpenAI) embeds them → the repositories persist them, advancing `Filing` status at each step

**State Management:**
- Trading: `TradingState` TypedDict (`app/agent/trading/domain/trading_state.py`). Nodes return only deltas. Channels that several nodes append to (`cost_events`, `debate_turns`, `risk_turns`, `analyst_failures`) use the `operator.add` reducer. The Postgres checkpointer saves after every super-step.
- RAG: stateless requests. Persistent state lives in Postgres through a psycopg pool (`app/infrastructure/repositories/db.py`).

## Key Abstractions

**Port:**
- Purpose: Wraps one external dependency behind async functions
- Examples: `app/agent/trading/infrastructure/price_data_port.py`, `news_data_port.py`, `debate_port.py`, `risk_port.py`, `synthesis_port.py`
- Pattern: Module-level async functions, not classes. LLM ports call `call_with_schema_retry` and then `record_cost_event`

**Router:**
- Purpose: Pure function from state to the name of the next node
- Examples: `app/agent/trading/application/debate_router.py::next_debate_step`, `risk_router.py::next_risk_step`
- Pattern: No I/O. Wrapped by `_guarded()` in `graph.py`

**Repository / Query:**
- Purpose: Write-side aggregate persistence vs read-side cross-aggregate queries
- Examples: `app/infrastructure/repositories/filing_repo.py`, `app/infrastructure/queries/corpus_status.py`
- Pattern: Raw SQL through psycopg. Queries return frozen dataclasses

**Model role:**
- Purpose: One env var per LLM role, each falling back to `LLM_CLAUDE_MODEL`
- Examples: `app/infrastructure/llm/models.py::model_for`
- Pattern: `get_client(model)` returns a provider-routed client

## Entry Points

**API server:**
- Location: `app/main.py` (`uv run uvicorn app.main:app`)
- Triggers: HTTP. It must be running on :8000 before any agent or trading run
- Responsibilities: RAG endpoints and the trading run over HTTP

**RAG CLI:**
- Location: `app/cli.py` (`uv run python -m app.cli <cmd>`)
- Responsibilities: ingest, corpus-status, eval, extract-metrics

**Research agent:**
- Location: `app/agent/researcher.py::main` (`uv run python -m app.agent.researcher TICKER [--news ...]`)

**Trading CLI:**
- Location: `app/agent/trading/interface/cli.py::main`

**Model roster:**
- Location: `app/infrastructure/llm/models.py` (`uv run python -m app.infrastructure.llm.models`)

**Scripts / eval:**
- Location: `scripts/*.py` (probes, P9 battery, audit tools) and `eval/runner.py`, `eval/extract_runner.py`

## Architectural Constraints

- **Threading:** Single asyncio event loop. Everything is async (FastAPI, psycopg async pool, LangGraph `ainvoke`). The graph runs nodes sequentially and has no parallel branches.
- **Global state:** Settings read at import time: `LLM_CLAUDE_MODEL` (`model_for`), `LOOP_MAX_TURNS`, `MEMO_DIR`. Module-level model constants include `claude_model` in `app/llm.py` and `AGENT_MODEL` in `researcher.py`. The DB pool is a module global in `app/infrastructure/repositories/db.py`. `API_BASE` is hardcoded in `app/agent/tools.py`.
- **Env loading order:** Entry points must call `load_env()` before importing app modules (see the top of `app/main.py`, which uses `# noqa: E402`). The `scripts/` tools load `.env` with `override=True`.
- **Cross-system coupling:** The trading pipeline depends on the RAG server over HTTP (loopback), not in-process.
- **Checkpoint compatibility:** If node names change, existing threads can no longer be resumed. Use a fresh `--thread-id` (see the `build_trading_graph` docstring).

## Anti-Patterns

### Calling the clock inside a node

**What happens:** A node derives the date itself with `date.today()`.
**Why it's wrong:** Runs with a probe date become unverifiable and data leaks past the analysis date. This happened in the history of the fundamentals leg.
**Do this instead:** Read `state["as_of_date"]`, which is set once in `interface/runner.py::initial_state`.

### Trusting identifiers or counters from model output

**What happens:** Turn indexes, IDs or labels are taken from the LLM payload.
**Why it's wrong:** The model fabricates or reorders them.
**Do this instead:** Assign them in Python, as `debate_port.py` and `risk_port.py` do, and validate them with `domain/validation.py`.

### Returning accumulated lists from nodes

**What happens:** A node returns the full `cost_events` or `debate_turns` list.
**Why it's wrong:** The add-reducer duplicates every entry.
**Do this instead:** Return only the delta for this call (`trading_state.py` comments).

### Importing private helpers across layers

**What happens:** `app/main.py` imports `_fuse_across_queries` from `retrieval_service.py`.
**Do this instead:** Expose a public function or method on `RetrievalService`.

## Error Handling

**Strategy:** Fail loudly on contract violations and degrade explicitly on vendor failures.

**Patterns:**
- Vendor errors (`domain/errors.py::VendorError`) inside analyst nodes become `analyst_failures` entries plus memo `data_gaps`. They do not crash the run.
- `NodeBudgetExceeded` is caught by `_contain_node_budget` in `graph.py` and becomes `node_budget_breach`, which routes the run to `graceful_abort`.
- Schema violations are retried once through `retry_messages`, then `force_crash`.
- `MemoVerificationError` (`synthesis_port.py`) triggers when a memo's figures or verdict fail verification.
- `MissingSetting` is raised at import time for required env vars.

## Cross-Cutting Concerns

**Logging:** `print()` with bracketed prefixes (`[abort]`, `[fundamentals]`) is the operator-facing trace. `run_log.py` tees stdout to the vault. `logging.getLogger(__name__)` appears in some RAG and infrastructure modules. Every LLM call adds a JSONL cost line through `infrastructure/cost_log.py` and `researcher.log_cost` (path from `app/infrastructure/cost_log_path.py`).
**Validation:** Pydantic models at every LLM boundary (`domain/*`). Text sanitizing of third-party news is in `domain/sanitize.py`, and the injection canary tests live in `tests/agent/trading/test_injection_canary.py`.
**Authentication:** Endpoints that spend money depend on `require_api_key` (header checked against `APP_API_KEY`). CORS origins come from env (`app/main.py`).
**Cost control:** `RunBudget` (`domain/budget.py`) is enforced by `check_run_guards` on edges, by per-node caps inside ports (`structured_call.assert_within_budget`), and by the `stop_check` in the agent loop.

---

*Architecture analysis: 2026-09-27*
