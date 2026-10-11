# EDGAR Research

Ingests SEC EDGAR filings into a Postgres + pgvector corpus and answers questions over it,
from one grounded answer (`/ask`) up to a full fundamentals memo written by the Research
agent. Glossary: [CONTEXT.md](./CONTEXT.md). Architecture: [docs/architecture.md](./docs/architecture.md). Using it for real research:
[docs/using-it-for-research.md](./docs/using-it-for-research.md).

Run everything from the repo root, after the setup in the [root README](../../README.md#setup).

## HTTP API

Start the server. The Research agent's tools call it at a hardcoded `http://localhost:8000`,
so it must be up before any agent or trading run.

```bash
uv run uvicorn app.main:app --reload
```

| Endpoint | Spends | What it is for | Called by |
|---|---|---|---|
| `POST /ask` | LLM | Grounded Q&A: decompose, hybrid-retrieve, answer with citations, verify them | agent tool `ask_edgar` |
| `POST /extract` | LLM | Extract structured financial metrics for one filing | agent tool `extract_metrics` |
| `POST /ingest` | embeddings | Run the ingestion pipeline for one ticker | agent tool `ingest_ticker` |
| `POST /latest-filings` | — | List a ticker's filings on EDGAR and mark which are already in the corpus | agent tool `check_latest_filings` |
| `GET /corpus-status` | — | What is in the corpus, with integrity issues and searchable sections | agent tool `check_corpus` |
| `GET /health` | — | The commit this server process is running | agent tools, once per process |

`GET /health` is served by `app/main.py`; the rest by [api.py](./api.py).

**Common rules**

- **API key.** If `APP_API_KEY` is set, the endpoints that spend need a matching `X-API-Key`
  header (the agent's tools send it automatically). Unset, they are open, which is fine on
  `127.0.0.1`.
- **Unknown fields are a 422.** A misspelled field fails loudly instead of being dropped.
- **Tickers** are stripped and upper-cased; anything that is not a ticker is a 422.
- **`filed_before`** bounds results at an analysis date, so a historical run never sees
  filings published after it.
- **Usage header.** `/ask` and `/extract` report their token usage per model in an
  `X-LLM-Usage` response header, not in the body.

### `POST /ask`

```bash
curl -s localhost:8000/ask -H 'Content-Type: application/json' -d '{
  "question": "What were the main drivers of revenue growth?",
  "tickers": ["AVGO"], "filing_types": ["10-K"], "k": 8,
  "filed_before": "2026-03-01", "section_path_contains": ["Risk Factors"]
}'
```

Only `question` is required. Returns `answer`, the `citations` it used, `unverified` (figures
or quotes not found in the retrieved text), the `chunks` retrieved, and
`dropped_section_filter` when no chunk matched the section filter, which was then ignored.

### `POST /extract`

```bash
curl -s localhost:8000/extract -H 'Content-Type: application/json' -d '{
  "ticker": "FIG", "fiscal_period": "FY2025", "filing_type": "10-K", "filed_date": "2026-02-18"
}'
```

Retrieves within `filed_date` ± 30 days (override with `filed_after` / `filed_before`) and
returns `revenue`, `gross_margin_pct`, `gaap_net_income`, `free_cash_flow`,
`sbc_pct_of_revenue`, `net_dollar_retention`, `extraction_confidence` and `reasoning`.

### `POST /ingest`

```bash
curl -s localhost:8000/ingest -H 'Content-Type: application/json' \
  -d '{"ticker": "AVGO", "limit": 3, "since_year": 2023}'
```

`form_type` defaults to the filer's family (10-K for a domestic filer, 20-F for a foreign
one). `retry_failed: true` re-runs filings a previous ingest marked FAILED. Blocks until
done; returns `{"status": "ok", "ticker", "limit"}`.

### `POST /latest-filings`

```bash
curl -s localhost:8000/latest-filings -H 'Content-Type: application/json' \
  -d '{"ticker": "AVGO", "since_year": 2024, "filed_before": "2026-03-01"}'
```

Returns each filing's `form`, dates, `in_corpus` and `corpus_status`, plus counts of what is
new. `periodic_only` (default `true`) keeps 10-K/10-Q or 20-F and drops event filings such as
8-Ks; naming `form_types` explicitly overrides it.

### `GET /corpus-status`

```bash
curl -s 'localhost:8000/corpus-status?ticker=AVGO&filed_before=2026-03-01'
```

Both parameters are optional. Returns `summary`, `issues`, `per_filing` and
`sections_available`: the section names `/ask`'s `section_path_contains` will match.

### `GET /health`

```bash
curl -s localhost:8000/health    # {"status": "ok", "commit": "...", "dirty": false}
```

## CLI: `python -m app.edgar_research.cli`

```bash
uv run python -m app.edgar_research.cli --help
```

| Command | Spends | What it is for |
|---|---|---|
| `ingest TICKER [--type 10-K] [--limit 4] [--since YEAR] [--retry-failed]` | embeddings | Discover → download → parse → chunk → embed. Resumable: a rerun picks up at the last completed phase. |
| `corpus-status [--ticker T] [--verbose]` | — | Summary of the corpus and its integrity issues. Run it after every ingest: a filing can be `EMBEDDED` with far too few chunks. |
| `fetch TICKER [--type 10-K] [--limit 4] [--since-year YEAR]` | — | Download filings into the local cache without ingesting them. |
| `inspect-chunks HTML_PATH [--type 10-K] [--json-out] …` | — | Parse and chunk one cached filing and print the result, for tuning the chunker. |

```bash
uv run python -m app.edgar_research.cli ingest AVGO --type 10-K --limit 4 --since 2023
uv run python -m app.edgar_research.cli corpus-status --ticker AVGO --verbose
```

## CLI: the Research agent

Needs the API server running. The memo goes to stdout and tool traces to stderr, so
`2>/dev/null` yields a clean memo; memos are also saved to the vault (`MEMO_DIR`).

```bash
uv run python -m app.edgar_research.agent.researcher AVGO                     # full fundamentals checklist
uv run python -m app.edgar_research.agent.researcher AVGO --news "AVGO announces 10B buyback"
```

A full checklist run is the same one Trading's fundamentals analyst runs through
[fundamentals_memo.py](./fundamentals_memo.py), the only module other contexts may import.

## Scripts: `python -m app.edgar_research.scripts.<name>`

Measurement probes, run before changing retrieval. All need Postgres with an ingested corpus.
They spend on embeddings only; none calls an LLM.

| Script | What it answers |
|---|---|
| `gate_a_corpus_probe` | Does retrieval return filing text for every watchlist ticker, before an agent spends money asking? |
| `probe_fusion_ab [--pairs 40] [--k 8] [--shape agree\|split\|both]` | Does summing RRF scores across sub-queries beat taking the max? (known-item retrieval) |
| `probe_retrieval_rank_decay` | Does trimming `ask_edgar`'s `k` lose anything? Run before changing `ASK_EDGAR_K`. |

```bash
uv run python -m app.edgar_research.scripts.probe_fusion_ab --pairs 40 --k 8
```

## Migrations

Alembic, with `alembic.ini` at the repo root and revisions in [migrations/](./migrations/).

```bash
uv run alembic upgrade head
```
