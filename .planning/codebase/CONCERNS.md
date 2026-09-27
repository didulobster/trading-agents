---
last_mapped_commit: 8a7c506660f3af4394b728e0ea36e9b78d2baeb2
last_mapped_at: 2026-09-27
---
# Codebase Concerns

**Analysis Date:** 2026-09-27

Primary living sources of truth for known issues: `docs/trading-agent-known-gaps.md` (~3000 lines, phase-by-phase gap log) and `docs/code_review.md` (structural review of `app/`, 2026-09-20). Check them before re-diagnosing anything below.

## Tech Debt

**`ANALYST_OUTPUTS` in the wrong layer causes an import cycle:**
- Issue: the dict mapping analyst leg to `TradingState` key lives in the application layer; infrastructure ports import it upward. Cycle: `risk_nodes -> risk_port -> debate_port -> nodes -> synthesis_port`. Worked around with function-local imports.
- Files: `app/agent/trading/application/nodes.py:307`, `app/agent/trading/infrastructure/debate_port.py:66`, `app/agent/trading/infrastructure/risk_port.py:227`, `app/agent/trading/infrastructure/synthesis_port.py` (7 local `from app...` imports), `app/agent/trading/application/debate_router.py:32`
- Impact: deferred imports hide load-order errors until call time; new ports inherit the cycle.
- Fix approach: move `ANALYST_OUTPUTS` to `app/agent/trading/domain/trading_state.py`; convert local imports to top-level (finding #1 in `docs/code_review.md`).

**`researcher.py` and `debate_port.py` act as shared libraries:**
- Issue: `app/agent/researcher.py` is the de-facto vault/usage writer for the whole trading pipeline (7 importers); `debate_port.py` is reached into for `_private` names by `risk_port.py` and `synthesis_port.py`. ~20 `_private` names cross module boundaries.
- Files: `app/agent/researcher.py`, `app/agent/trading/infrastructure/debate_port.py`, `app/agent/trading/infrastructure/risk_port.py:51`, `app/agent/trading/infrastructure/synthesis_port.py`
- Impact: renaming a "private" helper breaks other ports; unclear ownership.
- Fix approach: extract vault/usage helpers and shared debate helpers into their own modules with public names.

**Very large modules:**
- Files: `app/agent/trading/infrastructure/debate_port.py` (1507 lines), `app/agent/tools.py` (1162), `app/agent/trading/infrastructure/synthesis_port.py` (953), `app/agent/trading/application/nodes.py` (923), `app/agent/researcher.py` (794), `app/agent/prompts.py` (720), `app/agent/trading/infrastructure/risk_port.py` (713), `app/main.py` (623)
- Impact: conflicts with the project rule "short modules, short functions"; hard to review.
- Fix approach: split along the lines in `docs/code_review.md` (guards, prompt builders, validators into separate modules).

**Small duplications (open from code review):**
- `as_of_date is None` guard x4 in `app/agent/trading/application/nodes.py` (~112,147,204,685)
- `/ask` and `/extract` repeat `RetrievalService` wiring in `app/main.py`
- Five `_dispatch` branches repeat the non-200 error shape in `app/agent/tools.py` (~601-785)
- `_QUOTE_LABEL` / `_strip_quote_label` copied in `app/agent/trading/domain/debate.py` and `app/agent/trading/domain/risk.py`
- 23 nested `async with` blocks across `app/infrastructure/repositories/*.py`
- Fix approach: extract one helper per duplication.

**`print()` used instead of logging in library code:**
- Issue: 91 `print(` calls in `app/`; 16 in `app/agent/trading/application/nodes.py` (e.g. synthesizer sample-dropped messages), 3 in `app/agent/tools.py`, 3 in `fundamentals_port.py`. CLI prints (`app/agent/trading/interface/cli.py`, 50) are fine.
- Impact: node diagnostics go to stdout from inside the API server (`/trading/analyze`), not to the log.
- Fix approach: use `logging.getLogger(__name__)` in non-CLI modules.

## Known Bugs

**Checkpoint can lag one debate turn behind the last completed turn:**
- Symptoms: after a crash at node entry, the resumed run re-executes the previous turn (one wasted LLM call, ~$0.0074).
- Files: `app/agent/trading/infrastructure/checkpointer.py`, `app/agent/trading/application/debate_nodes.py`
- Trigger: process death early in a super-step (documented Phase 5 gap 1 in `docs/trading-agent-known-gaps.md`).
- Workaround: none needed for correctness; transcript stays contiguous.

**Price fetch lookahead in historical probes (resolved in code; gap log stale):**
- Status: the gap log records price history not bounded by `as_of_date`, but both vendor paths now apply `_bound_to_as_of` (`_try_yfinance` line 136, `_try_finnhub` line 181). Only the gap-log entry needs closing.
- Files: `app/agent/trading/infrastructure/price_data_port.py`, `docs/trading-agent-known-gaps.md`

**News article bodies are not point-in-time:**
- Symptoms: Finnhub serves articles as they exist now; updated articles leak future information into historical runs.
- Files: `app/agent/trading/infrastructure/news_data_port.py`
- Workaround: none; needs a point-in-time archive.

**Memos contradict their own verdict / debaters never concede:**
- Symptoms: 7 of 34 vault memos contradict their verdict; across 249 debate turns 0 `concede` stances (modeling mismatch between per-turn stance and per-claim concession, see "The concession channel has never fired" in `docs/trading-agent-known-gaps.md`).
- Files: `app/application/verdict_consistency.py`, `app/agent/trading/domain/debate.py`, `app/agent/trading/infrastructure/debate_port.py`

## Security Considerations

**Spending endpoints are open when `APP_API_KEY` is unset:**
- Risk: `/ask`, `/extract`, `/ingest`, `/news-assess`, `/trading/analyze` spend provider money; `require_api_key` is opt-in and a no-op without the env var.
- Files: `app/main.py:228-248`
- Current mitigation: uvicorn defaults to 127.0.0.1; `docker-compose.yml` binds Postgres to loopback.
- Recommendations: fail closed when bound to a non-loopback host; keep `/latest-filings` (unguarded, hits EDGAR) in mind if exposed.

**Hardcoded dev DB password in CI:**
- Risk: low; `.github/workflows/tests.yml` uses a throwaway Postgres service password. Do not reuse it elsewhere.
- Files: `.github/workflows/tests.yml`

**Secrets:**
- `.env` exists (not read); template in `.env.example`. Provider keys, Finnhub key, `EDGAR_USER_AGENT`, `APP_API_KEY` are env-only.

## Performance Bottlenecks

**Fundamentals agent loop hits the turn cap:**
- Problem: Phase 9 measured 2 of 3 fundamentals runs exhausting `LOOP_MAX_TURNS`; cold tickers ingest from EDGAR on demand. Cost $0.21-0.45 per fundamentals run.
- Files: `app/agent/researcher.py:54,599`, `app/agent/tools.py`
- Cause: compound `ask_edgar` questions rank the answer chunk poorly, forcing extra turns.
- Improvement path: single-part questions, pre-ingest watchlist (`docs/watchlist.yaml`).

**Agent calls its own API over HTTP:**
- Problem: tools hit `API_BASE = "http://localhost:8000"` rather than calling services in-process.
- Files: `app/agent/tools.py:25`
- Cause: agent was built as an API client; requires a running, up-to-date server (stale-server guard at `tools.py:~575`).
- Improvement path: call application services directly or make `API_BASE` configurable.

**Majority-of-N risk verdict sampling multiplies cost:**
- Files: `app/agent/trading/application/nodes.py` (`RISK_VERDICT_SAMPLES` loop ~790)
- Cause: N synthesizer samples per run to stabilize verdicts.

## Fragile Areas

**Text/number guards (fabrication, citation, rounding):**
- Files: `app/application/number_matching.py`, `app/application/citation_verifier.py`, `app/application/memo_verifier.py`, `app/agent/trading/application/guards.py`, `app/agent/trading/domain/sanitize.py`
- Why fragile: unmeasured false-positive rate; each fix came from a live failure (rounding, percent, hyphenated compounds, units/ratio labels). Initial vault sweep: 1 true / 7 false.
- Safe modification: sweep the whole memo vault before shipping a guard change; add the live case as a test.

**Structured tool calls across providers:**
- Files: `app/agent/trading/infrastructure/structured_call.py`, `app/infrastructure/llm/client.py`, `app/infrastructure/llm/openai_compat.py`
- Why fragile: provider dialects differ (Sonnet 5 rejects `temperature`; GPT-5.x needs `max_completion_tokens` and `reasoning_effort="none"`; Sonnet strict schemas reject `minItems`/`maxItems` and int bounds; empty strings leak markup).
- Safe modification: verify model ids and params against the provider; tests in `tests/infrastructure/test_llm_provider.py`.

**Checkpoint serialization of domain types:**
- Files: `app/agent/trading/infrastructure/checkpointer.py`, `app/agent/trading/domain/*.py`
- Why fragile: an unregistered domain type serializes in-process and only fails when another process reads it back from Postgres.
- Test coverage: `tests/agent/trading/test_checkpoint_roundtrip.py` (needs Postgres; CI provides one).

**Broad `except Exception` sites:**
- `app/main.py:82`, `app/agent/tools.py:326,583`, `app/agent/trading/application/nodes.py:799`, `app/agent/trading/infrastructure/price_data_port.py:137,182`, `app/application/ingestion_service.py:119`, `app/infrastructure/build_info.py:29`. Each is intentional and commented; don't add more without the same justification.

## Scaling Limits

**News cap:**
- Current capacity: `MAX_ARTICLES` 300 (~68% of `NEWS_BUDGET_USD`).
- Limit: tickers with >300 in-window articles truncate newest-first, dropping event days.
- Scaling path: per-day quota in `app/agent/trading/infrastructure/news_digest_port.py`.

**Budget guard blind spots:**
- ~28% of fundamentals spend was unlogged (delegated cost now logged; verify). Budget assertions fire after batches are paid.
- Files: `app/agent/trading/domain/budget.py`, `app/agent/trading/infrastructure/cost_log.py`, `app/infrastructure/llm/pricing.py`

## Dependencies at Risk

**`tiktoken==0.8.0`:**
- Risk: no Python 3.14 wheel; source build needs Rust. Python pinned to 3.13 in `.python-version` and CI for this reason.
- Migration plan: bump tiktoken, then unpin Python.

**Old exact pins:** `fastapi==0.115.6`, `pydantic==2.9.0`, `pypdf==5.0.0`, `python-dotenv==1.0.0`, `uvicorn==0.32.0` in `pyproject.toml` — behind current releases while other deps float with `>=`.

**Single news vendor:** Finnhub only (`news_data_port.py`); outage kills the news node. Prices have yfinance/Finnhub fallback. `yfinance` is an unofficial scraper and breaks periodically.

## Missing Critical Features

**Summary faithfulness verification:** nothing checks that model news summaries match article bodies (`news_digest_port.py`).

**Linting in CI:** ruff is used ad hoc (see recent commits) but not configured in `pyproject.toml` or run in `.github/workflows/tests.yml`.

## Test Coverage Gaps

**Live-model behavior:**
- What's not tested: suite stubs all provider calls; quality regressions (concessions, verdict/memo consistency, `evidence_quality`) only surface in paid runs via `scripts/`.
- Files: `scripts/run_p9_battery.py`, `scripts/p9_automated_gate.py`
- Risk: high run-to-run variance; one run pair proves nothing.
- Priority: Medium

**DB-dependent tests skip locally:**
- What's not tested: `tests/agent/test_ask_edgar_section_filter.py`, `tests/test_stale_server_guards.py`, checkpoint round-trip tests skip/fail without Postgres on `localhost:6432`.
- Risk: pass locally while broken; CI covers them.
- Priority: Low

**`eval/` and `scripts/` untested:** no tests for `eval/runner.py`, `eval/report.py`, or most `scripts/*.py` (only `test_audit_worksheet.py`). Priority: Low.

---

*Concerns audit: 2026-09-27*
