# Code review: `app/` — simplification

**Reviewed:** `main` at `543d020` (after #110, the stale-server guards), 2026-09-20.
**Scope:** `app/` only (~18.5k lines, 92 modules). Tests, `eval/`, `scripts/` and `migrations/` were read only where they decide whether something in `app/` is dead.
**Question asked:** not "is this correct?" but "what is here twice, here for nothing, or here in the wrong place?" Correctness findings are in the PR reviews; this pass reports only structure.
**Method:** an AST pass for definitions nothing references (counting `tests/`, `eval/`, `scripts/` as callers, so nothing is called dead because only a test uses it); `ruff` (F/B/SIM/RET/ARG/PIE/C4); an AST pass for `_private` names imported across module boundaries; an import-cycle trace; and a hand read of the six largest modules. Every claim below was checked against the tree — **[verified]** means I ran something, **[from code]** means I read it.

**Predecessor:** the previous review (broad, all-categories, 2026-09-12) is at `git show d82ce1c:docs/code_review.md`. Its High and Medium findings shipped; where an item of its Low section is still open it is folded in below rather than repeated.

**Suite at review time [verified]:** `3 failed, 960 passed, 10 skipped in 93s`. All three failures need a Postgres on `localhost:6432` that is not running in this checkout (`tests/agent/test_ask_edgar_section_filter.py` ×2, `tests/test_stale_server_guards.py::test_health_reports_the_running_commit`). They are environmental and unrelated to anything here — but the third is a new test that did not need a database until #110, and it is already filed as a review finding against that PR.

---

## Summary

`app/` has been through real simplification passes and it shows: `structured_call.py` holds the one forced-tool-call contract all three ports used to copy, `_save_output` is the one vault writer, `number_matching.py` is the one token-anchored matcher, and the pre-refactor PDF pipeline is gone. There is no large-scale duplication left to delete.

What remains is one structural problem and a tail of small ones. The structural problem is **module placement**, not module content: three things that belong low in the stack live high in it, and every module that needs them reaches upward. That is what produces this repo's most distinctive smell — **20 `_private` names imported across module boundaries [verified]**, and **9 function-local imports written to dodge a cycle [verified]**, each with a comment apologising for itself. Both numbers go to near zero by moving three definitions; almost no logic changes.

The rest is genuine but small: four copies of one guard, two copies of one wiring block, five copies of one error shape, 23 copies of one `with`, eight dead definitions and thirteen unused imports.

### Priority list

| # | Size | Finding | Where |
|---|---|---|---|
| 1 | Medium | A 5-line dict in the wrong layer causes a real import cycle and 9 deferred imports | `application/nodes.py:307` |
| 2 | Medium | `researcher.py` is the de-facto vault/usage library for the whole trading pipeline | `agent/researcher.py`, 7 importers |
| 3 | Medium | `debate_port.py` is a de-facto shared library, reached into privately 6 times | `risk_port.py:51`, `synthesis_port.py:495,606` |
| 4 | Small | The same `as_of_date is None` guard, written out four times | `application/nodes.py:112,147,204,685` |
| 5 | Small | `/ask` and `/extract` repeat the same six-line `RetrievalService` wiring | `main.py:289,361` |
| 6 | Small | Five `_dispatch` branches repeat the same non-200 error shape | `agent/tools.py:601-785` |
| 7 | Small | `_QUOTE_LABEL` + `_strip_quote_label` + a 17-line comment, copied verbatim | `domain/debate.py:69`, `domain/risk.py:65` |
| 8 | Small | 23 nested `async with` in six repositories | `infrastructure/repositories/*.py` |
| 9 | Small | Eight definitions nothing calls | various |
| 10 | Small | 13 unused imports, 1 duplicate import, 1 module shadowed by a local | various, `main.py:37/44`, `main.py:51/366` |
| 11 | Small | Three comments that now describe the opposite of what the code does | `tools.py:487,665,674`, `number_matching.py:18` |
| 12 | Small | Two parameters that are passed and never read | `researcher.py:110`, `runner.py:114` |

---

## 1. A 5-line dict in the wrong layer causes a real import cycle — `application/nodes.py:307` [verified]

`ANALYST_OUTPUTS` maps each analyst leg to the `TradingState` key it fills:

```python
ANALYST_OUTPUTS = {
    "fundamentals": "fundamentals_report",
    "technical":    "technical_report",
    "news":         "news_digest",
}
```

That is a statement about the *state shape*. It lives in `application/nodes.py`, the 923-line module that runs the legs. Three infrastructure modules need it, so `debate_port.py:61` imports it at module level — and `nodes.py` imports `synthesis_port`, which is downstream of `debate_port`. The cycle is `risk_nodes → risk_port → debate_port → nodes → synthesis_port`, and the codebase already knows:

- `synthesis_port.py:38-42` — *"Imports from debate_port are LOCAL to each function rather than at module level … debate_port imports `ANALYST_OUTPUTS` from application.nodes at its OWN module level, and nodes.py imports from this module, so a top-level import here completes the cycle."*
- `nodes.py:633-635` — *"Local import: risk_nodes → risk_port → debate_port → nodes (for ANALYST_OUTPUTS) is a real cycle at module-load time."*

So one dict in the wrong module is the stated cause of **9 function-local imports** across 4 files [verified]: `nodes.py:636`, `risk_port.py:228`, `synthesis_port.py:254, 298, 405, 461, 495, 606, 640`.

**Suggested change.** Move `ANALYST_OUTPUTS` to `domain/trading_state.py`, beside the `TradingState` keys it names. Nothing else moves. `debate_port.py:61` then imports from `domain`, which imports nothing back, the cycle is gone, and the nine deferred imports become ordinary top-level ones — deleting nine comments explaining why they could not be.

While there, fold in the line that is duplicated *because* of the awkward placement: `order = list(ANALYST_OUTPUTS) + ["sentiment"]` appears at both `debate_port.py:451` and `risk_port.py:231` [verified]. Make it `REPORT_ORDER` in the same new home.

## 2. `researcher.py` is the trading pipeline's vault library — `agent/researcher.py` [verified]

`app/agent/researcher.py` is the standalone research-agent CLI. It is also where seven trading modules get their infrastructure:

| Imported from `researcher` | By |
|---|---|
| `_save_output` | `debate_port`, `risk_port`, `news_digest_port`, `decision_memo_port`, `fundamentals_port`, `technical_interpreter_port` |
| `UsageSummary` | `cost_log`, `structured_call`, `news_digest_port`, `technical_interpreter_port`, `risk_port`, `fundamentals_port` |
| `log_cost`, `_compute_cost`, `AGENT_MODEL`, `StopCheck` | `fundamentals_port`, others |
| `_ticker_arg` | `trading/interface/cli.py:15` |
| `_build_news_prompt` | `main.py:559` (function-local, to avoid importing the agent at app start) |

`_save_output` is a 40-line function that owns the vault layout, the run-folder convention and the last ticker-validation before a path is written. Six modules outside its package import it *by its private name*. A leading underscore that six other packages ignore is documentation that is actively false, and it hides the real dependency: every port depends on the research CLI module being importable, with its argparse, its watchlist loading and its prompt constants.

**Suggested change.** Two small modules, no behaviour change:

- `app/agent/vault.py` — `save_output` (public), which `researcher.py` re-exports or simply calls.
- `UsageSummary` / `_compute_cost` / `log_cost` alongside the existing `app/domain/token_usage.py`, which is already the module for "what a call cost."

`researcher.py` shrinks toward being what its name says, and `trading/infrastructure/*` stops importing the research CLI to write a file.

## 3. `debate_port.py` is a de-facto shared library — `risk_port.py:51`, `synthesis_port.py:495,606` [verified]

`risk_port` imports four private names from `debate_port` at module level (`_flag_debate_numbers`, `_inline_refs`, `_flag_direction_claims`, `_norm`); `synthesis_port` imports two more, function-locally, to dodge finding #1's cycle. `debate_port` in turn reaches privately into `technical_interpreter_port` for `_PERIOD_LABEL` and `_flag_unmatched_numbers_against` (`debate_port.py:71`).

These are not accidents — they are the right functions being reused. The problem is that the reuse is undeclared: `debate_port.py` is 1502 lines of which roughly a third (`_inline_refs`, `_norm`, `check_quotes`, the number-flagging block, `report_texts`/`quotable_texts`) is infrastructure the other two ports run on, mixed in with the bull/bear debate itself.

**Suggested change.** Lift the shared third into a sibling — `trading/infrastructure/evidence.py` is the natural name, since every one of those helpers answers "is this claim/figure backed by the evidence pack?" Make the names public there. `debate_port` drops to the debate, `risk_port`'s private import block becomes a normal one, and with #1 done, `synthesis_port`'s seven deferred imports become one ordinary import of the new module.

This is the largest of the three, and it is the one to do **last** — it is a genuine reorganisation, where #1 and #2 are moves.

## 4. The same `as_of_date` guard, four times — `nodes.py:112, 147, 204, 685` [verified]

Each of the four nodes opens with the same shape: read `state.get("as_of_date")`, and if it is `None`, raise a `ValueError` whose message says "refusing to run unbounded … is a lookahead bug," above a 3–6 line comment explaining the rule. Roughly 40 lines say one thing four times.

**Suggested change.** One helper in `application/guards.py` — which already exists for run-level guards and imports nothing that would cycle:

```python
def require_as_of(state: TradingState, leg: str) -> date:
    """The run's analysis date, or refuse. A bound a node can forget to
    apply is not a bound: every source in the pipeline is capped at this
    date, and an unbounded read is lookahead, not a missing default."""
    as_of = state.get("as_of_date")
    if as_of is None:
        raise ValueError(
            f"as_of_date missing from TradingState — refusing to run the "
            f"{leg} leg unbounded. Reading a source without an explicit "
            f"upper bound is a lookahead bug."
        )
    return as_of
```

Each call site becomes `as_of = require_as_of(state, "fundamentals")`. The four incident comments collapse into the one docstring — keep the specifics (`nodes.py:105-109` on the fundamentals leg being the last to adopt the rule) as a one-line note at its site.

## 5. `/ask` and `/extract` repeat the same wiring — `main.py:289, 361` [verified]

Both endpoints open with the identical six lines (down to the same trailing whitespace):

```python
embedder = _embedder()
chunk_repo = ChunkRepository()
decomposer = _decomposer()
retrieval = RetrievalService(
    embedding_service=embedder, 
    chunk_repo=chunk_repo,
    decomposer=decomposer)
```

`_embedder()` and `_decomposer()` already exist at `main.py:93-98` for exactly this reason; the composite was never given the same treatment. `/ask` needs `chunk_repo` separately for its section check, so return both or let it construct its own.

**Suggested change.** Add `_retrieval()` beside them, returning the configured service. Two call sites lose five lines each, and there is one place to change when the service gains a dependency. (`cli.py:421`, `eval/runner.py:149` and three `scripts/` probes build it too, with four different argument styles — out of scope here, but the factory is where they should eventually point.)

## 6. Five `_dispatch` branches repeat one error shape — `agent/tools.py:601-785` [verified]

Each HTTP tool branch ends the same way:

```python
resp = await http.post(f"{API_BASE}/ask", json=payload)
if resp.status_code != 200:
    return f"Error from /ask: {resp.status_code} — {resp.text[:500]}"
```

Five branches, five copies of the check and the 500-char truncation [verified: `grep -c "Error from /"` → 5].

**Suggested change.** One helper inside the `async with` block:

```python
async def _call(method: str, path: str, label: str, **kw) -> str | httpx.Response:
    """The response, or the error string the agent should read instead."""
    resp = await http.request(method, f"{API_BASE}{path}", **kw)
    if resp.status_code != 200:
        return f"Error from {label}: {resp.status_code} — {resp.text[:500]}"
    return resp
```

Worth doing mostly because the failure text is agent-visible: five copies is five chances for one tool to report a failure in a shape the model has not been taught to read.

## 7. A validator copied between two domain modules — `domain/debate.py:69`, `domain/risk.py:65` [verified]

`_QUOTE_LABEL`, `_strip_quote_label` and the 17-line comment above them are byte-identical in both modules. `risk.py:49-52` says so explicitly: *"Same fix as domain/debate.py's `_QUOTE_LABEL`, same reason and same duplication trade as `_BLANK_SENTINELS` above."*

For `_BLANK_SENTINELS` that trade is right — three lines, and the modules are otherwise independent. For `_QUOTE_LABEL` it is not, because the bulk of what is duplicated is not the three lines of code but the incident record above them: a dated NFLX case, the reasoning for stripping in the domain rather than in the check, and the scope limits. Two copies of an incident note drift, and the copy that drifts is the one nobody was looking at.

**Suggested change.** `domain/sanitize.py` already exists in the same package for exactly this kind of text hygiene. Move `_QUOTE_LABEL`/`strip_quote_label` there with the comment, import it in both. Leave `_BLANK_SENTINELS` alone — the existing note argues its case correctly.

## 8. 23 nested `async with` in six repositories — `infrastructure/repositories/*.py` [verified]

Every repository method opens `async with get_connection() as conn:` then `async with conn.cursor() as cur:` on the next line. Ruff flags 23 of them, in `chunk_repo` (7), `filing_repo` (5), `metrics_repo` (4), `listed_security_repo` (3), `section_repo` (2) and `document_repo` (2). Nothing else in `app/` trips this rule.

**Suggested change.** Not `ruff --fix` (which merely joins them into one long line). Add to `repositories/db.py`, beside `get_connection`:

```python
@asynccontextmanager
async def cursor():
    async with get_connection() as conn, conn.cursor() as cur:
        yield cur
```

Every method then opens `async with cursor() as cur:`, one indent level shallower. The few methods that need `conn` itself (for an explicit transaction) keep using `get_connection` directly.

## 9. Eight definitions nothing calls [verified]

An AST pass over `app/` + `tests/` + `eval/` + `scripts/` + `migrations/`, counting attribute access as a call, finds these referenced nowhere but their own definition:

| Definition | Where |
|---|---|
| `FinancialMetricsResponse` (a response model no route declares) | `main.py:182` |
| `RunLog.by_ticker` | `trading/domain/validation.py:90` |
| `ListedSecurityRepository.get_by_ticker` | `repositories/listed_security_repo.py:36` |
| `FilingRepository.list_by_status` | `repositories/filing_repo.py:61` (named only in a neighbouring docstring) |
| `MetricsRepository.list_by_ticker` | `repositories/metrics_repo.py:160` |
| `MetricsRepository.list_by_tickers` | `repositories/metrics_repo.py:173` |
| `Chunk.is_embedded` | `domain/chunk.py:26` |
| `FilingStatus.is_terminal` | `domain/values.py:20` |
| `structured_call.crash_marker` | `trading/infrastructure/structured_call.py:151` |

The last one is worth a second look rather than a plain delete: it was extracted as the shared way to read a crash point, and then no port adopted it — all three still read `os.getenv` inline (`debate_port.py:175-176`, `risk_port.py:80-81`, `synthesis_port.py:100`). Either use it in the three ports or drop it.

`llm/client.py:230 is_anthropic` is exported through `llm/__init__.py` and called by nothing [verified], but it is a public API-surface predicate beside `resolve_provider`; leaving it is defensible.

## 10. Unused and duplicate imports [verified]

13 unused imports: `debate_port.py:53` (`create_with_temperature_fallback`), `fundamentals_port.py:5` (`json`), `risk_port.py:47` (`RiskScore`), `extraction_service.py:2` (`os`), `cli.py:8` (`asdict`), `domain/chunk.py:2` (`Field`), `edgar/client.py:6` (`sqlite3.connect`), `edgar/ticker_resolver.py:3` (`date`), `llm/openai_compat.py:26` (`os`), `filing_repo.py:1` (`date`), `section_repo.py:1` (`Json`), `main.py:51`, `main.py:56` (`RetrievedChunk`).

Two in `main.py` deserve naming separately:

- **`format_citation_tag` is imported twice**, at `main.py:37` and again at `main.py:44`.
- **`main.py:51` imports the `metrics_repo` *module*, which is unused — and `main.py:366` binds a local `metrics_repo = MetricsRepository()` inside `/extract`.** Harmless today because nothing reads the module-level name. It is the setup for an `UnboundLocalError`: any future function that reads `metrics_repo.something` before assigning it will fail at runtime, not at import. Drop the module import; the class is already imported.

`ruff --fix` handles the plain 11; do the `main.py` two by hand.

## 11. Three comments that describe the opposite of the code [verified]

- **`tools.py:487` / `665` / `674`.** `USE_STUBS = False` is preceded by *"Toggle to False in step 2 once the HTTP branches are wired"*, and the branch below reads *"STEP 2: real HTTP calls. Un-stub by setting USE_STUBS = False"* — instructions to reach a state the file is already in. A third, `"STEP 2: confirm this route/param exists, or add it to main.py"`, sits above a route that has existed for months.
  Note that **`USE_STUBS` and `_stub()` are not dead** — `tests/agent/test_ask_edgar_budget.py:103` sets it `True` to test the budget refusal without a server [verified], which contradicts the previous review's "scaffolding, delete it." Keep the mechanism, delete the three stale comments, and say what it is for: a test seam. Five tests also `monkeypatch.setattr(tools, "USE_STUBS", False)` when `False` is already the default — harmless, but they are pinning a default rather than changing anything.
- **`number_matching.py:15-18`** ends *"folding them in is a separate change (docs/code_review.md, Medium #6)."* In the review it points at, Medium #6 is the dead PDF pipeline — the reference drifted when that document was rewritten. Worse, the change it invites is one this review recommends **against** (see below). Replace the pointer with the reason the three matchers stay separate.

## 12. Two parameters passed and never read [verified]

- **`researcher.py:110` `_build_news_prompt(ticker, news_text)`** never uses `news_text`. Not a bug: both callers (`main.py:562`, `researcher.py:770`) pass the headline again in the *task* message, which is where the prompt's "Read the news/announcement below" actually points. Drop the parameter, or the next reader will spend the same ten minutes proving it is not a bug.
- **`runner.py:114` `_describe_stale_budget(values, max_usd, wall_clock_timeout_s)`** never reads `wall_clock_timeout_s`, though it does compare the inherited `max_usd` against the flag just given. A resume whose inherited deadline disagrees with the `--timeout` just passed is exactly the disagreement this function exists to report, so this is either a missing check or a leftover parameter. Decide which; do not leave it as an argument that does nothing.

---

## Checked, and deliberately not recommended

Rejecting these is part of the review — each looks like duplication and is not.

- **The three number matchers** (`debate_port._flag_debate_numbers`, `technical_interpreter_port._flag_unmatched_numbers_against`, `application/number_matching`). They implement three *different rules* — exact containment, indicator-tolerance with percent/delta transforms, and token-anchored variant matching — and each docstring records live false positives that produced its tolerance. `debate_port`'s explains why a tolerance band goes blind on dense numeric text; `number_matching`'s explains why a substring check let fabricated figures verify. `synthesis_port._numeric_guard:495` already delegates to `debate_port`'s rather than writing a fourth. Merging them would silently re-tolerance two guards. The only change wanted here is deleting the stale invitation at `number_matching.py:18`.
- **`_BLANK_SENTINELS` in `domain/debate.py:49` and `domain/risk.py:41`.** Three lines, argued for in place, and the two domains are otherwise independent. Correct call.
- **`_maybe_crash` in the three ports.** Three lines each, each naming its own env var and label; the shared part (`force_crash`) is already shared.
- **`_assert_within_budget` in the three ports.** Each is a four-line call into `structured_call.assert_within_budget` supplying its own ceiling and message. The shared part is already shared; what is left is configuration.
- **`save_*_transcript` / `_format_*_markdown` across five ports.** They all route through one `_save_output`; the formatters render genuinely different documents.
- **`cli.py`'s thin `@app.command` wrappers around `asyncio.run(_impl(...))`.** That is the Typer idiom, not duplication.
- **`app/llm.py`.** A 92-line module at the top level while its peers sit under `application/` — but it has one importer and one job, and moving it is churn with no reader benefit. Mentioned only so the next reviewer can skip it.

## Suggested order

Cheap and independent first; the reorganisation last.

- [ ] `ruff check app --select F401 --fix`, then the two `main.py` import fixes by hand (#10)
- [ ] Delete the three stale `STEP 2` comments and fix the `number_matching.py` pointer (#11)
- [ ] Delete the eight uncalled definitions; decide `crash_marker`'s fate (#9)
- [ ] Resolve the two dead parameters (#12)
- [ ] `require_as_of` in `guards.py`, four call sites (#4)
- [ ] `_retrieval()` in `main.py`, two call sites (#5)
- [ ] `cursor()` in `db.py`, 23 call sites (#8)
- [ ] `_call` helper in `tools.py._dispatch` (#6)
- [ ] Move `_QUOTE_LABEL` to `domain/sanitize.py` (#7)
- [ ] **Move `ANALYST_OUTPUTS` to `domain/trading_state.py`; convert the 9 deferred imports to top-level ones and delete their apologies (#1)**
- [ ] Extract `vault.py` / usage helpers out of `researcher.py` (#2)
- [ ] Split the shared third of `debate_port.py` into `evidence.py` (#3)

Everything above #1 is local and safely reviewable in one PR each. #1 is the one with real leverage: it is a five-line move that deletes nine workarounds and the comments explaining them.
