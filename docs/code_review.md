# Code review: trading-agents

**Reviewed:** `main` at `e751df3` (after #80, the per-model delegated-cost fix), 2026-09-11.
**Scope:** `app/` (~19.6k lines with `scripts/` and `eval/`), `tests/` (~12k lines), CI, migrations, config.
**Method:** I read the HTTP API, the research agent and its tool layer, the trading graph and nodes, the budget and cost path, the synthesis, risk and debate ports (the large heuristic guards were skimmed, not audited line by line), retrieval, the SQL repositories, ingestion, EDGAR, parsing and chunking, the verifiers, provider routing, config, and CI.

Findings are labelled **[verified]** when I confirmed them against data, logs or a reproduction, and **[from code]** when they come from reading the code without running the failing path. No code was changed for this review.

---

## Summary

This codebase is careful about the things that usually go wrong in LLM pipelines:
- **Point-in-time data:** `as_of_date` is enforced on every data source, with post-assertions for lookahead.
- **Provenance:** every figure is traced back to the tool output that produced it.
- **Accounting:** cost events are deduplicated by id, the disk log is reconciled against state, and budgets are per run.
- **Fabrication guards:** they flag problems rather than hiding them.
- **The "why" behind decisions:** most non-obvious choices are explained next to the code, often with the live incident that motivated them.

The test suite (723 tests, CI against a real pgvector Postgres) matches that care.

The weaknesses are at the **edges** rather than the core:
- The HTTP API was built for the CLI's workflow and has not kept up with it.
- The budget guard can't see inside the two most expensive nodes.
- Retrieval, which everything downstream depends on, has a hybrid search whose keyword half almost never returns results, and a chunker that splits financial tables away from their headers.
- The guard logic that matters most, deciding whether a number is real, has four separate implementations of different strength.

### Priority list

| # | Severity | Finding | Where |
|---|---|---|---|
| 1 | High | `/trading/analyze` spends money, then fails | `app/main.py:413-439` |
| 2 | High | Budget and deadline guards are blind inside the fundamentals and synthesizer nodes | `graph.py`, `nodes.py:650`, `researcher.py` |
| 3 | High | The BM25 half of hybrid retrieval returns nothing for 93% of queries | `chunk_repo.py:187` |
| 4 | Medium | Local API: no auth, `CORS *`, unvalidated ticker used as a file path | `main.py:62`, `researcher.py:224` |
| 5 | Medium | Financial tables are split from their headers; statements are filed under the wrong Item | chunker, parser |
| 6 | Medium | `calculate` provenance check uses the substring matching the verifier already replaced | `tools.py:950` |
| 7 | Medium | Ingestion: FAILED is terminal; chunking is not idempotent | `ingestion_service.py` |
| 8 | Medium | Synthesizer and ports: one non-guard error discards already-paid samples; budget checks crash the run | `nodes.py:667`, ports |
| 9 | Medium | `ingest_ticker` sends `limit: null`; `extract_metrics` date bounds are ignored | `tools.py:573`, `main.py:235` |
| 10 | Medium | Resumed runs never write a `run_summary` | `cli.py:118-174` |
| 11 | Medium | Module-level run state is unsafe in the server process | `tools.py`, `researcher.py` |
| 12 | Medium | Config: 13 `load_dotenv` calls with mixed override; settings that look configurable but do nothing | many |
| 13 | Medium | Wall clock is the binding constraint, and independent work runs one call at a time | `researcher.py:531`, `nodes.py:650` |
| 14+ | Low | Dead code, duplication, small bugs and hygiene | see Low section |

---

## High

### 1. `/trading/analyze` spends money, then fails [from code]
`app/main.py:432` starts the graph with `{"ticker": ticker}` only. Compare with the CLI (`app/agent/trading/interface/cli.py:164-171`), which also passes `as_of_date`, `run_id` and `budget`, sets a `recursion_limit`, and wraps the run in `vault_run()`.

What happens on a new thread:
- The graph starts with `fundamentals`, which runs the full research agent. That's the most expensive node, typically $0.02–0.45 and minutes of work, and it saves a memo.
- The next node, `technical_node`, raises `ValueError("as_of_date missing …")`. So does `news_node`. The request returns 500 after the spend.
- **No budget means no guard.** `_guarded()` treats a missing budget as "opted out" (`graph.py:39-43`).
- **No `run_id`** means none of the cost lines can be grouped into a run.
- **Aborted-run crash:** even with the state fixed, `result["decision_memo"]` raises `KeyError` on a run that ended in `graceful_abort`.
- **Long blocking request:** a full run holds one HTTP request open for 6–15 minutes.

No test calls any endpoint (see Testing), so nothing catches this.

**Suggested fix:** build the initial state with one shared function used by both the CLI and the API, and pass `recursion_limit`. Either return a job id and run the graph in the background, or remove the endpoint until it's needed.

### 2. The budget guard can't see inside the expensive nodes [from code, consistent with logged incidents]
`check_run_guards` runs only on graph edges. Its docstring says a run can overshoot `max_usd` "by at most one call's cost" (`guards.py:33`). That holds for nodes that make a single call, but not for these two:
- **`fundamentals`** runs `run_agent`: up to `LOOP_MAX_TURNS=45` model turns, plus up to 30 `/ask` and `/extract` calls, each of which runs its own LLM calls on the server. Neither the spend nor the deadline is checked until the node returns. The CLI already concedes this (`cli.py:60-63`: "the run-level guards can only fire between nodes, which on this graph means after the fundamentals stage has already been paid for"). The MSFT resume incident recorded there spent $0.4069 and produced no memo.
- **`synthesizer`** runs three samples, and samples 2 and 3 each include a fresh 9-turn risk panel (`nodes.py:650-677`), all within one node.

The deadline has the same blind spot: a fundamentals loop that hangs is invisible to `deadline_utc` until it ends.

**Suggested fix:** pass a small "may I spend" callback (the budget plus the running total) into `run_agent`. Check it once per turn and before each `ask_edgar`, then end the loop the same way `MAX_TURNS` does, so the agent still writes a memo. In `synthesizer_node`, check the budget before each extra sample, and report a sample skipped for budget as a data gap. Then correct the docstring.

### 3. The keyword (BM25) half of hybrid retrieval almost never contributes [verified]
`search_by_text` uses `plainto_tsquery('english', question)` (`chunk_repo.py:187, 215`), which joins every word with **AND**. A chunk matches only if it contains *every* word of the question.

The fixed metric queries are nine-word bags ("revenue gross profit cost of revenue gross margin net income loss"), and the agent's questions are long compound sentences, so this almost never matches:
- **Server log of the 2026-09-11 split-setup ACN run:** 43 hybrid retrievals, **40 with zero BM25 hits**, 2 with one hit, 1 with five.
- **Extraction replay:** all four `METRIC_QUERIES` logged `15 vector + 0 bm25`.

So in practice "hybrid" retrieval is vector-only, plus a wasted query. Two knock-on effects:
- **Meaningless similarity scores:** `_reciprocal_rank_fusion` replaces cosine similarity with the RRF score (`retrieval_service.py:204`), which is what the agent sees as `sim=0.016` on every citation. Similarity tells it nothing about result quality.
- **Merging by RRF score:** `retrieve_full` ranks results from different sub-queries by comparing their fused RRF scores.

**Suggested fix:** use `websearch_to_tsquery`, or build an OR query (`to_tsquery` with terms joined by `|`) and rank with `ts_rank_cd`. Keep the cosine similarity on the result (for example as `vector_similarity`) next to the fused rank. Measure before and after with `eval/runner.py`.

---

## Medium

### 4. Local API: no auth, wide-open CORS, unvalidated ticker used in file paths [from code]
- `allow_origins=["*"]` with `allow_headers=["*"]` and no authentication (`main.py:60-65`). A browser page on any origin can send cross-origin requests to `http://localhost:8000/ingest`, `/ask`, `/extract`, `/news-assess` and `/trading/analyze`, and each of those spends API credits. Browsers' local-network protections may block some of this, depending on browser and version, but the server itself grants permission.
- The ticker is never validated. It goes from `TradingAnalysisRequest` to `_save_output`, where `parent = MEMO_DIR / ticker` (`researcher.py:224`) accepts `../`. `Path.home()/'memos'/'../../../TMP/X'` resolves outside the vault, and `.upper()` doesn't stop that on macOS's case-insensitive filesystem. The fundamentals node saves before the `/trading/analyze` failure in #1, so this is reachable today.
- `docker-compose.yml` publishes Postgres on all interfaces (`6432:5432`) with the password `dev`.

**Suggested fix:** validate the ticker against a pattern like `^[A-Z][A-Z0-9.\-]{0,9}$` at every entry point. Restrict CORS to the UI's origin, or remove it. Add a shared-secret header for the endpoints that spend money. Bind Postgres to `127.0.0.1:6432:5432`.

### 5. Financial tables are split away from their headers, and statements land under the wrong section [verified]
The chunker keeps sections whole but splits long ones into pieces of about 600 tokens. When it does, the table header isn't repeated in the next chunk.

ACN's FY2025 10-K cash-flow statement is chunk 110, which holds the heading, the column years and the first rows, plus chunk 111, which holds the totals with no header. A model given chunk 111 alone can't tell which column is which year. This is part of why the answer model reported cash-flow rows as "not in the excerpts" on 2026-09-11. The replay showed Luna misreading them even when both chunks were supplied.

The parser also assigns the entire F-pages block to `['Part IV', 'Item 16', 'Form 10-K Summary']`. As a result:
- Citations read `§Item 16` for financial statements.
- `section_path_contains=['Item 8']` filtering would miss them.
- The research agent's "which section is this from" reasoning is wrong for every figure in the statements.

**Suggested fix:**
- **Tables:** make chunking table-aware. Keep a table whole when it fits; otherwise repeat the table's title and column-header row at the top of every chunk of it.
- **F-pages:** detect the financial-statements block (the "Report of Independent Registered Public Accounting Firm" / "Consolidated … Statements" headings) and give it its own section path.
- **Re-index:** re-chunk the six ACN filings, then compare eval recall before and after.

### 6. `calculate` provenance uses the substring matching the verifier already replaced [from code]
`citation_verifier.py`'s module docstring explains why substring matching was replaced by whole-token matching: a made-up "$420.5M" verified because "$3,420.5" appeared somewhere in the text. `tools.py:950` (`_appears_in_output`, which is check 4 of `validate_calculate_inputs`) still uses `any(v in corpus …)`. So any declared input whose digits appear inside a larger number counts as "retrieved". That covers every two-digit integer, because they appear inside years, and many one-decimal values. The fiscal-period proximity check (check 5) matches the same way.

The codebase has four separate "is this number real" implementations, each with different semantics:
- `tools._variants` / `_appears_in_output`: plain substring match.
- `citation_verifier`: whole-token match plus tolerance bands.
- `debate_port._flag_debate_numbers` / `_is_rounding_of`: exact containment plus a rounding check.
- `technical_interpreter_port._flag_unmatched_numbers_against`.

**Suggested fix:** make one shared number-matching module, with the token-anchored matcher as its core. Give each caller a named policy (exact, rounding-tolerant, scale-tolerant) instead of its own implementation, and point the `calculate` checks at it.

### 7. Ingestion: FAILED is terminal, and chunking is not idempotent [from code]
- **FAILED is permanent.** `_advance_filing` exceptions mark the filing FAILED (`ingestion_service.py:97-101`). On the next run, `_upsert_filing` returns the existing row, and none of the status branches match FAILED, so the filing is skipped forever. Nothing in `app/` resets it. The domain model's state machine (`Filing.transition_to()` / `fail()`, which requires going back through DISCOVERED) is never called; `mark_status` writes the status straight to the database. A transient embedding error or 429 therefore permanently removes a filing from the index until someone edits the database.
- **Chunks can be duplicated.** `_chunk` inserts chunks, commits, and only then marks the filing CHUNKED. It doesn't check for existing chunks (`_parse` does check for existing sections), and `chunks` has no unique constraint on `(section_id, chunk_index)`. A crash between the insert and the status update duplicates the filing's chunks on the next run, and those duplicates then compete in retrieval.

**Suggested fix:**
- **Failed filings:** add an ingest option (say `--retry-failed`) that moves FAILED back to DISCOVERED through the domain method.
- **Chunk duplicates:** make `_chunk` delete any existing chunks for the document before inserting, or skip documents that already have them, as `_parse` does. Add a unique index so a duplicate fails loudly.
- **Per-filing transaction:** insert chunks and update the status in one transaction.

### 8. One non-guard error discards samples that already succeeded; budget checks crash the run [from code]
- **Only guard errors are dropped.** `synthesizer_node` handles `SynthesisFabricationError` and `SynthesisReferenceError` per sample (`nodes.py:667`). Anything else escapes: a second schema failure (`ValidationError` from `_call_with_schema_retry`), a provider 400 (`LLMBadRequestError`), or a timeout. That discards samples that already passed and were paid for, and the node's cost events go with it. The comment at `nodes.py:679-686` acknowledges the cost loss for the all-dropped case only.
- **Per-port budget checks crash the run.** The checks in the ports (`_assert_within_budget` in debate, risk, synthesis and news) `raise AssertionError` after the money is spent. That ends the run with a traceback. A run-level breach, by contrast, routes to `graceful_abort` and writes a partial memo. The two budget mechanisms behave differently for what is the same condition from the user's point of view.

**Suggested fix:** treat any exception in a sample as "dropped", with the reason recorded, and keep its cost events. Have per-port budget breaches raise a dedicated `BudgetExceeded` that the graph converts into the graceful-abort path.

### 9. Tool arguments vs. what the server does with them [from code]
- **`ingest_ticker` sends `limit: null`.** `_strictify` makes every optional property nullable and required, so a model that doesn't choose a limit sends `limit: null`. `inputs.get("limit", 3)` (`tools.py:573`) returns `None`, not 3, and `IngestRequest.limit: int = 3` then rejects `null` with a 422. `_strictify`'s docstring ("an explicit null behaves exactly as the previously-absent key did") is not true for `.get(key, default)` calls. It works today only because the tool description tells the model to pass `limit=3`.
- **`extract_metrics`'s date bounds are ignored.** The tool offers `filed_after` / `filed_before` (`tools.py:164-165`) and forwards them (`json=inputs`, `tools.py:624`). `/extract` ignores both and always uses `filed_date ± 30 days` (`main.py:235-236`). The agent is being offered a control that does nothing.
- **Stale comment.** The comment at `main.py:240` says the decomposer may run during extraction retrieval. `gather_extraction_chunks` uses `retrieve_hybrid`, which never calls it.

**Suggested fix:** after `_strictify`, read optional arguments as `inputs.get(k) or default`. Either honour the date bounds in `/extract` or remove them from the tool schema.

### 10. Resumed runs never write a `run_summary` [from code]
`invoked` is set to `True` only on the new-run branch (`cli.py:155`), and `log_run_summary` runs only when `invoked` is true (`cli.py:174`). A resumed run that completes, which is exactly the crash-and-resume case the cost reconciliation was designed for, leaves no `run_summary` line. Queries over `kind=run_summary` then undercount runs and spend.

**Suggested fix:** set `invoked = True` on the resume branch too. Mark the summary as a resume so a query can tell the two apart.

### 11. Module-level run state is unsafe in the server [from code]
Several things are per-run module globals:
- `tools._RETRIEVED_TEXT`, `_CALC_RESULTS`, `_REJECTED_CALC_ATTEMPTS`, `_SESSION_LOG`, `_DELEGATED_USAGE`, `_ASK_EDGAR_CALLS` and `_CALC_CACHE`.
- `researcher._RUN_STAMP`.

The comment at `tools.py:805` states the assumption: "one agent run per process — true for the CLI". It stops being true in the API server. `/news-assess` and `/trading/analyze` run `run_agent` inside the server process, and any two overlapping requests (or one of them plus the agent's own tool calls back to the same server) share and reset each other's provenance record and `ask_edgar` budget. Wrong provenance defeats the calculate guard and the memo verifier without any error being raised.

**Suggested fix:** move this state into a `RunContext` object that `run_agent` creates and passes through `execute_tool`. Until then, reject overlapping agent runs in the server.

### 12. Configuration hygiene [verified]
- **Inconsistent `load_dotenv`.** It's called in 13 places, some with `override=True` (`main.py`, `llm.py`, `checkpointer.py`, the scripts) and some without (`researcher.py`, `cli.py`, `models.py`). So whether a shell variable or `.env` wins depends on which module happens to load first. With `override=True` loaded early, a command-line override of any variable that's also in `.env` is silently ignored. Load it once at each entry point, without override.
- **Missing variables crash at import.** `LOOP_MAX_TURNS` and `MEMO_DIR` are read with `os.environ[...]` at import time (`researcher.py:42, 58`), so any importer crashes with a bare `KeyError` (the README warns about this). A small settings object, validated at startup, would give one clear error instead.
- **Settings that do nothing.** This is the trap `models.py`'s docstring describes fixing, recurring:
  - `EMBEDDING_MODEL` is read only by dead modules (`app/ingest.py`, `app/retrieve.py`). `EmbeddingService` hard-codes `text-embedding-3-small` (`embedding_service.py:10`).
  - `OPENAI_MODEL` is read by nothing.
  - `scripts/run_p9_battery.py` records both in every battery manifest, so the reproducibility record carries two settings that had no effect.
- **Redundant branch.** `model_for` has an `if` whose branches return the same expression (`models.py:84-86`).
- **Wrong checklist size.** `.env.example` sizes `LOOP_MAX_TURNS` for a "7-item checklist"; the analyst prompt defines 12 items.

### 13. Wall clock is the binding constraint, and independent work runs one call at a time [from code]
Full runs take 350–920 s against an 1800 s deadline (cost has ample headroom; time does not). Four places run independent work one call at a time:
- **Agent tool calls.** `run_agent` awaits each tool call in turn (`researcher.py:529-538`). On 2026-09-11 Luna issued 6–7 `ask_edgar` calls per turn, and each one blocks the next.
- **Synthesizer samples.** The three samples, including two extra 9-turn risk panels, are independent but run in sequence (`nodes.py:650`).
- **Sub-query retrieval.** `retrieve_full` and `retrieve_with_decomposition` retrieve sub-queries one after another.
- **Per-request clients.** Every request builds a new `EmbeddingService`, new `QueryDecomposer` and new provider clients, so no HTTP connection pool is reused.

**Suggested fix:** use `asyncio.gather` for tool calls in the same turn. The provenance record is append-only, so record results in the model's order after the gather. Also gather the synthesizer samples, and the sub-query retrievals. Build clients once, at app startup. Parallel samples would take effect only after #2's per-sample budget check, otherwise three concurrent panels could overshoot together.

---

## Low

**Dead or stale code**
- `app/db.py`, `app/ingest.py`, `app/retrieve.py` and `app/db_postgres.py` are the pre-refactor PDF pipeline. `app/ingest.py` writes to a `chunks(source, …)` schema that no longer exists. `app/chunk.py` is imported only by these and by an unused import in `app/llm.py`.
- **`app/__init__.pyc` is committed**, and it's Python 2.7 bytecode (magic `03f3 0d0a`). Delete it and add `*.pyc` to `.gitignore`.
- **Unused or leftover code:**
  - `FinancialMetricsResponse` (`main.py:105`).
  - A duplicate `format_citation_tag` import (`main.py:18, 25`).
  - `USE_STUBS` and the "STEP 2" scaffolding comments in `tools.py`.
  - `MetricsRepository(session_factory=None)`, whose parameter is unused.
  - `from sqlite3 import connect` (`edgar/client.py:6`).
  - `Filing.transition_to` / `fail`, never called (see #7).

**Duplication across the ports**
- `_accumulate` is byte-identical in `debate_port`, `risk_port` and `synthesis_port`.
- Each port also has its own `_tool_block`, `_extract`, `_CORRECTION`, `_retry_messages`, `_submit`, `_maybe_crash` and `_assert_within_budget`.
- A shared "forced tool call with one schema retry, cost accounting and a crash hook" helper would remove a few hundred lines. It would also make #8's handling consistent in one place.

**Small bugs**
- **`--test` crash.** `python -m app.agent.researcher --test` crashes after the run: `mode` is never assigned on the test path (`researcher.py:637`).
- **Unguarded `content[0]`.** `resp.content[0].text` is read without a check (`llm.py:72`, `query_decomposer.py:160`). The OpenAI adapter returns no content blocks when the provider sends no text, for example when output is cut off at the token limit. That raises `IndexError`, a 500 from `/ask`.
- **Silent price-fetch failures.** `price_data_port` swallows all yfinance and Finnhub exceptions without logging (`:124, :156`), so a rate limit looks the same as "no data".
- **Deprecated event-loop call.** `asyncio.get_event_loop()` inside a coroutine (`edgar/client.py:94, 97`); use `get_running_loop()`.
- **Truncated filing history.** `list_filings` reads only the `filings.recent` part of EDGAR's filing list and ignores older history in `filings.files`, so older filings are silently missing when `since` goes far back.

**Correctness risks worth a note**
- **`calculate` returns a bare number with no unit.** Inputs are normalised to ones, so a difference of two thousands-denominated figures comes back 1000× larger than the source table's scale, with nothing saying so. That leaves the memo one misreading away from a 1000× error. Return the unit with the number, or normalise to the smallest declared scale.
- **`chunk_repo.search_by_embedding`'s docstring is inaccurate.** It says the filters run as a bitmap index scan before the HNSW scan, but pgvector doesn't combine indexes that way. With a selective filter it either sorts the filtered rows exactly or filters after the approximate scan, and the second can return fewer than `k` rows as the index grows. Consider `hnsw.iterative_scan` (pgvector ≥ 0.8), or exact search when a ticker filter is present.

**Dependencies and eval**
- **Undeclared dependencies.** `pyyaml` (in `researcher.py` and `eval/`) and `pandas` are imported directly but installed only as dependencies of other packages (`uvicorn[standard]`/`langchain-core`, and yfinance). Declare them.
- **Fragile eval gold sets.** They're keyed by serial chunk IDs, which change on every re-ingest; the test set is gitignored, and eval isn't in CI. Keying gold sets by `(accession, section_path, text hash)` would survive re-ingestion.

**Documentation**
- **Diverging duplicates.** `architecture.md` exists at the root (644 lines) and in `docs/` (711 lines), and the two differ. `trading-agent-known-gaps.md` and `watchlist.yaml` are also duplicated, as byte-identical copies, pending #81.
- **Typos in the `/ask` prompt.** The system prompt in `app/llm.py` has several ("the enough", "generate knowledge", "premable", an unclosed quote). They're harmless, but it's the prompt behind every `/ask`.

---

## Testing

**Strengths:**
- Wide unit coverage of the guards, routers, reducers, checkpoint round-trips (against real Postgres in CI), provider translation and cost accounting.
- Tests are named after the incident they pin, which makes intent obvious.

**Gaps:** each of these would have caught a finding above.
- **No HTTP endpoint tests.** A FastAPI `TestClient` smoke test of `/trading/analyze` with stubbed ports would have caught #1, and one of `/ingest` with `limit: null` would have caught #9.
- **No SQL-level retrieval tests.** Nothing tests `search_by_text` or hybrid fusion against the database. A single "BM25 returns at least one hit for a query copied from a chunk" test would have caught #3.
- **No ingestion tests** for idempotency (re-running after a partial chunk insert) or for retrying a FAILED filing (#7).
- **No chunker test on a table larger than one chunk** (#5).
- **Resume path.** The CLI test for resuming doesn't check that a `run_summary` gets written (#10).
- **A test that depends on a local file.** `test_manifest_merge.py:80` reads `docs/validation/…` and skips when the file is absent, which it currently is in this working tree.

---

## Suggested order of work

1. **Close the exposure (#1, #4).** Fix `/trading/analyze` or remove it. Validate the ticker, tighten CORS, and bind Postgres to localhost. This is small and removes the only paths where money can be spent from outside the machine.
2. **Make the budget guard reach inside nodes (#2, #8, #10).** This is the property the cost tracking exists to provide.
3. **Fix retrieval quality (#3, #5).** Fix the BM25 query, make chunking table-aware, and fix the F-pages section label. Measure with `eval/` before and after. This is likely the largest quality lever for the fundamentals gaps seen on 2026-09-11.
4. **Make ingestion robust (#7).**
5. **Consolidate number matching and the port boilerplate (#6, Low/duplication).**
6. **Clean up config and dead code (#12, Low).**
7. **Parallelise (#13)** once #2 is in, since parallel samples make the in-node budget checks more important.

---

## Fix checklist

`[x]` = done and tested, `[~]` = in progress, `[ ]` = not started. Each High item ships as its own PR.

### High
**#1 `/trading/analyze`**: PR #82, merged
- [x] One shared "start or resume a run" function for both the CLI and the API: builds the initial state (`ticker`, `as_of_date`, `run_id`, `budget`), refuses a stale resume, and sets `recursion_limit`
- [x] Request accepts `as_of_date` (defaults to today at the boundary, as in the CLI), `max_usd` and `wall_clock_timeout_s`
- [x] Artifacts saved inside `vault_run()`, so one run gets one vault folder
- [x] An aborted run returns its termination reason instead of a `KeyError`
- [x] Endpoint tests using FastAPI `TestClient` with a stubbed graph
- [ ] Follow-up (not in this PR): run in the background and return a job id

**#2 Budget and deadline inside nodes**: PR #83, merged
- [x] `run_agent` accepts a stop check: evaluated before every model turn and every tool call; when it fires, the loop ends the way `MAX_TURNS` does, so the agent still writes a memo
- [x] Fundamentals port builds that check from the run budget, earlier spend, the agent's own usage and delegated usage (each priced at its own model's rate)
- [x] `synthesizer_node` checks the budget before each extra verdict sample; a skipped sample is recorded as a data gap
- [x] `guards.py` docstring corrected
- [x] Unit tests: the agent stops mid-loop, synthesis skips samples on a breach
- [x] Live test, ACN with `--max-usd 0.03`: the loop stopped at $0.0304, refused 7 `ask_edgar` calls, wrote its memo, and the run ended `budget_exceeded` at $0.0377. The overshoot is the one forced memo call.

**#3 BM25 half of hybrid retrieval**: PR #84, merged
- [x] `search_by_text` matches ANY term (OR), while keeping `plainto_tsquery`'s stemming and escaping
- [x] Cosine similarity kept alongside the fused RRF score, and shown to the agent as `sim=` instead of the RRF value
- [x] Unit test for the query shape and for RRF preserving the vector similarity
- [x] Measured against the local corpus before and after (SQL only, no LLM spend). Result: queries with zero keyword hits went from 51/51 to 0/51. Answering chunks in the fused top 8: cash-flow questions 37 → 42, internal-control questions 6 → 11. Distinct-term and IDF rankings were measured too and did no better, so the simplest one shipped.
- [ ] Follow-up: `ask_edgar` can't pass a filing-type or date filter, so a question about "the FY2025 10-K" also retrieves 10-Qs and other years

All three High PRs merged together pass 750 tests (1 skipped).

### Medium
- [ ] #4 Validate the ticker at every entry point; restrict CORS; shared-secret header on endpoints that spend money; bind Postgres to 127.0.0.1
- [ ] #5 Table-aware chunking (repeat table title and header row); give the F-pages block its own section; re-chunk ACN; compare eval results
- [ ] #6 One shared number-matching module (token-anchored); point the `calculate` checks at it
- [ ] #7 `--retry-failed` through the domain state machine; idempotent `_chunk`; unique index on `(section_id, chunk_index)`; one transaction per filing
- [ ] #8 Drop a synthesis sample on any exception and keep its cost; per-port budget breach becomes a graceful abort
- [ ] #9 Read optional tool arguments as `inputs.get(k) or default`; honour or remove the `extract_metrics` date bounds; fix the stale comment
- [ ] #10 Write a `run_summary` for resumed runs
- [ ] #11 `RunContext` object instead of module globals; reject overlapping agent runs in the server until then
- [ ] #12 One `load_dotenv` per entry point; settings validated at startup; wire or remove `EMBEDDING_MODEL`/`OPENAI_MODEL`; fix `model_for` and the "7-item" note
- [ ] #13 Gather same-turn tool calls, synthesis samples and sub-query retrievals; build clients once at startup

### Low
- [ ] Delete the dead PDF-pipeline modules, `app/__init__.pyc` (add `*.pyc` to `.gitignore`) and unused symbols
- [ ] Shared structured-call helper for the debate, risk and synthesis ports
- [ ] `researcher --test` crash; guard `content[0]`; log the price-fetch exceptions; `get_running_loop`; read EDGAR's `filings.files`
- [ ] `calculate` returns a unit; fix the pgvector filtering docstring and consider `hnsw.iterative_scan`
- [ ] Declare `pyyaml`/`pandas`; key eval gold sets by content instead of chunk id
- [ ] Merge the duplicate docs; fix the prompt typos
