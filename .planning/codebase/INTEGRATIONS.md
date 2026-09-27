---
last_mapped_commit: 8a7c506660f3af4394b728e0ea36e9b78d2baeb2
last_mapped_at: 2026-09-27
---
# External Integrations

**Analysis Date:** 2026-09-27

## APIs & External Services

**LLM providers (all paid; never call without the user's permission):**
Routing is by model-id prefix in `_PROVIDERS` in `app/infrastructure/llm/client.py`. Credentials are validated at client construction (`ProviderNotConfigured`), not first call.
- Anthropic (`claude-*`) - SDK: `anthropic`; Auth: `ANTHROPIC_API_KEY`
- DeepSeek (`deepseek*`) - SDK: `openai` with `base_url=https://api.deepseek.com` (`DEEPSEEK_BASE_URL`); Auth: `DEEPSEEK_API_KEY`; uses a `thinking` param
- OpenAI (`gpt-*`, `o1`, `o3`, `o4`) - SDK: `openai`; Auth: `OPENAI_API_KEY`; sends `max_completion_tokens` and `reasoning_effort` for `gpt-5.*` (`app/infrastructure/llm/openai_compat.py`)
- OpenAI-compatible gateway - selected via `LLM_PROVIDER=openai-compatible`; `LLM_BASE_URL`, `LLM_API_KEY`
- Every call's cost is priced from `app/infrastructure/llm/pricing.py` and logged by `app/agent/trading/infrastructure/cost_log.py` (JSONL in `docs/cost-log-YYYY-MM.jsonl`, path from `app/infrastructure/cost_log_path.py`). Add new models to the pricing table or the per-run budget cannot fire.

**Embeddings:**
- OpenAI embeddings API - `app/application/embedding_service.py`, model `EMBEDDING_MODEL` (default `text-embedding-3-small`, 1536 dims); Auth: `OPENAI_API_KEY`

**SEC EDGAR (free):**
- `https://data.sec.gov/submissions/CIK{cik}.json`, `https://www.sec.gov/Archives/edgar/data/...` - `app/infrastructure/edgar/client.py`
- `https://www.sec.gov/files/company_tickers.json` - `app/infrastructure/edgar/ticker_resolver.py`
- Client: `httpx`; Auth: none, but `EDGAR_USER_AGENT` (name + email) required; ~8 req/s limit. Local cache: `EDGAR_CACHE_DIR`.

**Market data:**
- yfinance (Yahoo, unauthenticated) - primary daily prices, `_try_yfinance` in `app/agent/trading/infrastructure/price_data_port.py`
- Finnhub - price fallback via `finnhub.Client` (`_try_finnhub`, same file) and company news via `httpx` to `https://finnhub.io/api/v1/company-news` (`app/agent/trading/infrastructure/news_data_port.py`); Auth: `FINNHUB_API_KEY` (free tier works)
- All vendor requests are bounded by `--as-of`; never fetch beyond it.

## Data Storage

**Databases:**
- PostgreSQL 16 + pgvector (`pgvector/pgvector:pg16`, `docker-compose.yml`, `127.0.0.1:6432`, db `rag`)
  - Connection: `POSTGRES_DATABASE_URL` (RAG corpus), `TRADING_CHECKPOINT_DB_URI` (LangGraph checkpoints)
  - Client: psycopg 3 `AsyncConnectionPool` (`app/infrastructure/repositories/db.py`), raw SQL repositories in `app/infrastructure/repositories/`; `AsyncPostgresSaver` in `app/agent/trading/infrastructure/checkpointer.py`
  - Schema: Alembic migrations in `migrations/versions/` (pgvector init, tsvector for BM25, financial_metrics, unique chunk index)

**File Storage:**
- Local filesystem only: memos in `MEMO_DIR`, cost logs in `docs/`, run logs (`app/agent/trading/infrastructure/run_log.py`), EDGAR cache, `data/`

**Caching:**
- None external. EDGAR download cache on disk; the RAG corpus acts as a cache (ingested from EDGAR on demand).

## Authentication & Identity

**Auth Provider:**
- Custom, optional: `APP_API_KEY` checked against `X-API-Key` header on money-spending routes (`SPENDS_MONEY` dependency in `app/main.py`). Unset = open.
- CORS: `CORS_ALLOW_ORIGINS` (default Vite dev server `http://localhost:5173`).

## Monitoring & Observability

**Error Tracking:**
- None

**Logs:**
- stdlib `logging`; per-run cost JSONL (`docs/cost-log-*.jsonl`) and run logs.

## CI/CD & Deployment

**Hosting:**
- None (local only)

**CI Pipeline:**
- GitHub Actions `.github/workflows/tests.yml`: ubuntu, pgvector/pg16 service, `uv sync --frozen`, `uv run pytest -q -rs`. No provider keys; `LLM_CLAUDE_MODEL=deepseek-v4-flash` with stubbed call layer.

## Environment Configuration

**Required env vars:**
- `LLM_CLAUDE_MODEL`, `LOOP_MAX_TURNS`, `MEMO_DIR`, `POSTGRES_DATABASE_URL`, `TRADING_CHECKPOINT_DB_URI`, `EDGAR_USER_AGENT`, plus the API key for whichever provider the configured models resolve to, and `FINNHUB_API_KEY` for news.

**Secrets location:**
- `.env` (gitignored). `.env.example` documents all variables without values.

## Webhooks & Callbacks

**Incoming:**
- None. HTTP API endpoints in `app/main.py`: `POST /ask`, `/extract`, `/ingest`, `/latest-filings`, `/news-assess`, `/trading/analyze`; `GET /health`, `/corpus-status`.

**Outgoing:**
- None. The research agent's tools call the local API (sending `X-API-Key` when set) — `app/agent/tools.py`.

---

*Integration audit: 2026-09-27*
