---
last_mapped_commit: 8a7c506660f3af4394b728e0ea36e9b78d2baeb2
last_mapped_at: 2026-09-27
---
# Codebase Structure

**Analysis Date:** 2026-09-27

## Directory Layout

```
trading-agents/
├── app/                          # All application code (package root)
│   ├── main.py                   # FastAPI app (RAG + /trading/analyze)
│   ├── cli.py                    # Typer RAG CLI
│   ├── config.py                 # load_env / require_env / MissingSetting
│   ├── llm.py                    # /ask answer-generation prompt + call
│   ├── domain/                   # RAG entities & value objects
│   ├── application/              # RAG services + verifiers
│   ├── infrastructure/           # RAG adapters
│   │   ├── edgar/                # SEC client, ticker resolver
│   │   ├── parsing/              # filing HTML → sections
│   │   ├── chunking/             # sections → chunks
│   │   ├── repositories/         # write-side persistence (psycopg)
│   │   ├── queries/              # read-side queries (frozen dataclasses)
│   │   ├── llm/                  # provider routing, model roles, pricing
│   │   ├── build_info.py
│   │   └── cost_log_path.py
│   └── agent/                    # EDGAR research agent
│       ├── researcher.py         # tool-use loop (run_agent), CLI main
│       ├── tools.py              # agent tools → HTTP to localhost:8000
│       ├── prompts.py            # system prompts incl. ANALYST_SYSTEM_PROMPT
│       └── trading/              # multi-agent trading pipeline
│           ├── domain/           # pure Pydantic types/rules, TradingState
│           ├── application/      # graph nodes, routers, guards, indicators
│           ├── infrastructure/   # *_port.py, graph.py, checkpointer, logs
│           └── interface/        # cli.py, runner.py
├── tests/                        # pytest; mirrors app/ layout
│   ├── agent/trading/            # trading tests
│   ├── application/ infrastructure/ agent/
│   ├── fixtures/                 # CSV/JSON fixtures
│   └── conftest.py
├── migrations/                   # Alembic (env.py, versions/)
├── eval/                         # retrieval/extraction eval harness
├── scripts/                      # one-off probes, P9 battery, audit tools
├── docs/                         # tracked docs + watchlist; cost logs ignored
├── data/                         # local synced data (gitignored)
├── .github/workflows/tests.yml   # CI
├── docker-compose.yml            # Postgres 16 + pgvector on :6432
├── alembic.ini, pyproject.toml, uv.lock, .python-version (3.13)
├── README.md, architecture.md, trading-agent-known-gaps.md
└── .env.example                  # documented env vars (.env is gitignored)
```

## Directory Purposes

**`app/domain/`:**
- Purpose: RAG domain model
- Contains: `filing.py`, `document.py`, `section.py`, `chunk.py`, `listed_security.py`, `values.py` (Ticker, `normalize_ticker`), `token_usage.py`

**`app/application/`:**
- Purpose: RAG use cases and verification
- Key files: `ingestion_service.py`, `retrieval_service.py`, `embedding_service.py`, `extraction_service.py`, `query_decomposer.py`, `citation_verifier.py`, `memo_verifier.py`, `verdict_consistency.py`, `number_matching.py`, `citations.py`

**`app/infrastructure/`:**
- Purpose: Adapters for SEC, Postgres, parsing and LLMs
- Key files: `edgar/client.py`, `parsing/filing_parser.py`, `chunking/section_chunker.py`, `repositories/db.py`, `repositories/chunk_repo.py`, `queries/corpus_status.py`, `llm/client.py`, `llm/models.py`, `llm/pricing.py`, `llm/openai_compat.py`
- Subpackages each keep their own `models.py` for adapter-local types

**`app/agent/`:**
- Purpose: EDGAR research agent, which the trading fundamentals leg reuses
- Key files: `researcher.py` (`run_agent`, `vault_run`, `log_cost`), `tools.py`, `prompts.py`

**`app/agent/trading/domain/`:**
- Purpose: Trading types and rules with no I/O
- Key files: `trading_state.py`, `decision_memo.py`, `debate.py`, `risk.py`, `budget.py`, `fundamentals_report.py`, `technical_report.py`, `news_digest.py`, `sanitize.py`, `validation.py`, `errors.py`

**`app/agent/trading/application/`:**
- Purpose: Nodes, routers and deterministic logic
- Key files: `nodes.py`, `debate_nodes.py`, `risk_nodes.py`, `debate_router.py`, `risk_router.py`, `guards.py`, `risk_ledger.py`, `technical_indicators.py`

**`app/agent/trading/infrastructure/`:**
- Purpose: I/O ports and graph assembly
- Key files: `graph.py`, `structured_call.py`, `cost_log.py`, `run_log.py`, `checkpointer.py`, `fundamentals_port.py`, `price_data_port.py`, `news_data_port.py`, `news_digest_port.py`, `technical_interpreter_port.py`, `debate_port.py`, `risk_port.py`, `synthesis_port.py`, `decision_memo_port.py`

**`app/agent/trading/interface/`:**
- Purpose: Trading entry and run lifecycle
- Key files: `cli.py`, `runner.py`

## Key File Locations

**Entry Points:**
- `app/main.py`: FastAPI (`uv run uvicorn app.main:app`)
- `app/cli.py`: RAG CLI (`uv run python -m app.cli ...`)
- `app/agent/researcher.py`: research agent (`uv run python -m app.agent.researcher TICKER`)
- `app/agent/trading/interface/cli.py`: trading run
- `app/infrastructure/llm/models.py`: prints the model roster

**Configuration:**
- `app/config.py`, `.env.example`, `pyproject.toml`, `alembic.ini`, `docker-compose.yml`, `docs/watchlist.yaml`

**Core Logic:**
- `app/agent/trading/infrastructure/graph.py`: graph topology
- `app/agent/trading/application/nodes.py`: analysts and synthesizer
- `app/agent/trading/infrastructure/debate_port.py`: the largest file (~1500 lines), holding debate LLM calls and figure containment checks

**Testing:**
- `tests/` mirrors `app/`. Trading tests are in `tests/agent/trading/test_<module>.py`, and fixtures are in `tests/fixtures/`

## Naming Conventions

**Files:**
- snake_case modules: `retrieval_service.py`, `chunk_repo.py`
- Suffixes by role: `*_service.py` (RAG application), `*_repo.py` (repositories), `*_port.py` (trading adapters), `*_nodes.py` / `*_router.py` (graph pieces)
- Tests: `test_<subject>.py`
- Migrations: `<revhash>_<description>.py`

**Directories:**
- Layer names are `domain/`, `application/`, `infrastructure/` and `interface/`, and the same names repeat inside `app/agent/trading/`

## Where to Add New Code

**New trading analyst / graph node:**
- Types: `app/agent/trading/domain/<name>_report.py`, plus a field on `TradingState`
- I/O: `app/agent/trading/infrastructure/<name>_port.py` (LLM calls go through `structured_call.call_with_schema_retry` and `cost_log.record_cost_event`)
- Node: `app/agent/trading/application/nodes.py` (or a new `<area>_nodes.py`)
- Wiring: `ANALYST_CHAINS` or the node tuples in `app/agent/trading/infrastructure/graph.py`
- Tests: `tests/agent/trading/test_<name>_port.py`, `test_<name>_nodes.py`

**New RAG feature:**
- Service: `app/application/<name>_service.py`
- Persistence: `app/infrastructure/repositories/<name>_repo.py` (write) or `app/infrastructure/queries/<name>.py` (read), plus an Alembic migration in `migrations/versions/`
- Endpoint: `app/main.py`. CLI command: `app/cli.py`
- Tests: `tests/application/`, `tests/infrastructure/`

**New LLM role:**
- Add it to `app/infrastructure/llm/models.py`, add pricing in `pricing.py`, and document the env var in `.env.example` and `README.md`

**Utilities:**
- Pure trading helpers go in `app/agent/trading/domain/`. Pure RAG helpers go in `app/domain/values.py` or `app/application/`

**One-off experiments:**
- `scripts/<purpose>.py`. Never import these from `app/`

## Special Directories

**`migrations/`:**
- Purpose: Alembic schema history (pgvector, tsvector BM25 column, financial_metrics)
- Generated: partially (by revision). Committed: Yes

**`docs/`:**
- Purpose: design notes, tutorial, known gaps, `watchlist.yaml`
- Committed: Yes, except `docs/cost-log*.jsonl` and `docs/validation/**/*.std{out,err}` (run output)

**`data/`, `eval/results*`, `eval/*cache.json`, `/knowledge-base`:**
- Purpose: local data, eval output, caches
- Committed: No (gitignored)

**Vault (`MEMO_DIR`, relative to `$HOME`):**
- Purpose: memos, run logs and research output written by `runner.save_vault_artifacts` and `researcher.vault_run`
- Lives outside the repo

**`.claude/`:**
- Purpose: GSD tooling. It is not project code
- Committed: No (untracked)

---

*Structure analysis: 2026-09-27*
