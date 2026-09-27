---
last_mapped_commit: 8a7c506660f3af4394b728e0ea36e9b78d2baeb2
last_mapped_at: 2026-09-27
---
# Technology Stack

**Analysis Date:** 2026-09-27

## Languages

**Primary:**
- Python 3.13 (pinned in `.python-version`; `requires-python = ">=3.13"` in `pyproject.toml`) - all code in `app/`, `eval/`, `scripts/`, `tests/`, `migrations/`

**Secondary:**
- SQL (raw, via psycopg) - queries in `app/infrastructure/repositories/*.py` (pgvector `<=>`, `ts_rank` full-text in `app/infrastructure/repositories/chunk_repo.py`)
- YAML - `watchlist.yaml`, `docker-compose.yml`, `.github/workflows/tests.yml`

## Runtime

**Environment:**
- CPython 3.13. Do not move to 3.14: pinned `tiktoken==0.8.0` has no 3.14 wheel and fails a source build (documented in `.github/workflows/tests.yml`).
- Async-first: FastAPI + asyncio, `psycopg_pool.AsyncConnectionPool`, `httpx.AsyncClient`, `AsyncOpenAI`.

**Package Manager:**
- uv (0.12.x locally). Always `uv run ...`, `uv add ...`, `uv sync --frozen`.
- Lockfile: `uv.lock` present and committed.

## Frameworks

**Core:**
- FastAPI 0.115.6 (`fastapi[standard]`) + Uvicorn 0.32.0 - HTTP API in `app/main.py`
- LangGraph 1.2.11 - trading multi-agent graph in `app/agent/trading/infrastructure/graph.py`
- langgraph-checkpoint-postgres 3.1.2 - durable graph checkpoints (`app/agent/trading/infrastructure/checkpointer.py`)
- Pydantic 2.9.0 - request/response and domain models
- Typer 0.26.7 - EDGAR CLI in `app/cli.py`; trading CLI at `app/agent/trading/interface/cli.py`

**Testing:**
- pytest 9.1.1 (dev dependency group) - `tests/`; `pythonpath = ["."]` in `pyproject.toml`

**Build/Dev:**
- Alembic 1.19.1 + SQLAlchemy 2.0.52 - migrations only (`alembic.ini`, `migrations/env.py`, `migrations/versions/`); runtime DB access uses psycopg, not the ORM
- ruff - lint (`.ruff_cache/` present; no committed config, defaults)
- Docker Compose - local Postgres (`docker-compose.yml`)

## Key Dependencies

**Critical:**
- `anthropic` 0.122.0 - Claude models (`app/infrastructure/llm/client.py`)
- `openai` 3.1.0 - OpenAI, DeepSeek and any OpenAI-compatible endpoint via `AsyncOpenAI(base_url=...)` (`app/infrastructure/llm/openai_compat.py`); embeddings (`app/application/embedding_service.py`)
- `psycopg[binary,pool]` 3.3.4 + `psycopg-pool` - Postgres access (`app/infrastructure/repositories/db.py`)
- `pgvector` 0.5.0 - vector(1536) columns and similarity search
- `yfinance` 1.6.0 - primary price history (`app/agent/trading/infrastructure/price_data_port.py`)
- `finnhub-python` 2.4.29 - price fallback (same file); news via raw httpx (`app/agent/trading/infrastructure/news_data_port.py`)
- `pandas-ta-classic` 0.6.52 (+ pandas 3.0.5) - indicators in `app/agent/trading/application/technical_indicators.py`

**Infrastructure:**
- `httpx` 0.28.1 - SEC EDGAR and Finnhub HTTP (`app/infrastructure/edgar/client.py`)
- `beautifulsoup4`, `lxml`, `pypdf` 5.0.0 - filing parsing (`app/infrastructure/parsing/filing_parser.py`)
- `tiktoken` 0.8.0 - token counting for chunking (`app/infrastructure/chunking/section_chunker.py`)
- `asyncpg` 0.31.0 - async driver for Alembic/SQLAlchemy
- `python-dotenv` 1.0.0 - `.env` loading

## Configuration

**Environment:**
- `.env` (gitignored, present) loaded by entry points; `.env.example` is the canonical list of variables.
- Hard requirements: `LLM_CLAUDE_MODEL`, `LOOP_MAX_TURNS`, `MEMO_DIR` (read at import), `POSTGRES_DATABASE_URL` (first DB use). `TRADING_CHECKPOINT_DB_URI` for the trading graph.
- Use `require_env` from `app/config.py` for required variables (fails with the variable name).
- Per-role model ids: `LLM_ANSWER_MODEL`, `LLM_DECOMPOSER_MODEL`, `LLM_EXTRACTION_MODEL`, `TRADING_*_MODEL`; all fall back to `LLM_CLAUDE_MODEL`. Role table in `app/infrastructure/llm/models.py` (`uv run python -m app.infrastructure.llm.models` prints it).
- Pricing table in `app/infrastructure/llm/pricing.py`; override via `LLM_PRICING_OVERRIDES`.
- Tuning: `ASK_EDGAR_MAX_CALLS`, `ASK_EDGAR_K`, `AGENT_TOOL_CONCURRENCY`, `COST_LOG_DIR`, `EDGAR_CACHE_DIR`, `EMBEDDING_MODEL` (default `text-embedding-3-small`; changing it requires re-embedding).
- Dev hooks: `MOCK_FUNDAMENTALS`, `DEBATE_CRASH_AT_TURN`, `RISK_CRASH_AT_TURN`, `SYNTHESIS_CRASH_AT`, etc.
- `LANGGRAPH_STRICT_MSGPACK=true` set in `app/agent/trading/infrastructure/checkpointer.py`; new domain types in `TradingState` must be added to `ALLOWED_MSGPACK_MODULES` there.

**Build:**
- `pyproject.toml`, `uv.lock`, `alembic.ini`, `docker-compose.yml`, `watchlist.yaml`

## Platform Requirements

**Development:**
- uv, Python 3.13, Docker (pgvector/pgvector:pg16 on `127.0.0.1:6432`), then `uv run alembic upgrade head`.

**Production:**
- No deployment target. Runs locally: `uvicorn app.main:app`, `uv run python -m app.agent.trading.interface.cli <TICKER> --as-of ... --max-usd ...`.

---

*Stack analysis: 2026-09-27*
