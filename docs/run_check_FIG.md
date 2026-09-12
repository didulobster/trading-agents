# Live-run check: FIG, 2026-09-13

First full-pipeline run after the code-review fixes (PRs #102–#108). Purpose was to
verify the eleven High/Medium fixes against a real run rather than against the suite.

**Command:** `python -m app.agent.trading.interface.cli FIG --thread-id trading-FIG-postreview-20260913`
**Code:** `main` at `6d7c29f` (all six fix PRs merged) · **Corpus:** warm — FIG 6 filings, 789 chunks, all embedded
**Models:** answer + extraction on `deepseek-v4-flash`, everything else on `gpt-5.6-luna`

---

## Result

| | this run | prior FIG runs |
|---|---|---|
| Cost | **$0.159018** | $0.2616 · $0.2795 · $0.8628 |
| Wall clock | **286.2s** | 595s · 613s · 224s |
| Outcome | `completed` | `completed` ×3 |
| `cache_read_ratio` | **0.7233** | 0.658 · 0.711 · 0.665 |
| `cost_ledger_gap_usd` | **$0.00** | — |
| Schema violations / retries | **0** | — |
| Errors, crashes, aborts | **0** | — |

Verdict **HOLD** (samples `hold, sell, hold`, agreement 0.67), evidence quality 0.89,
8 data gaps — all of them real guard output, not noise. The debate hit its round cap;
the risk panel ran all three verdict samples. Nothing in the pipeline degraded.

The run is cheaper and faster than every prior FIG run, but the model routing also
changed between them, so **this is not a clean attribution to the review fixes.**

---

## Two problems found

### 1. The API server was 22 hours stale — the run used pre-review server code

`uvicorn app.main:app` had been running since **Sep 12 09:06:44**, which predates every
one of the six fix PRs (#108 merged Sep 13 07:02, five minutes before the run started).
The trading CLI ran current code; the server serving its 30 `ask_edgar` calls did not.

Caught by probing `POST /latest-filings` with `filed_before`, which the server **silently
ignored** — FastAPI drops unknown request fields, so the old `LatestFilingsRequest`
accepted the request and discarded the bound:

```
before restart:  echoed filed_before=None   5 filings   max 2026-08-05   past the bound: YES
after  restart:  echoed filed_before=...    2 filings   max 2025-11-05   past the bound: no
```

**Consequence for this run:** every `/ask` went through the *old* `retrieve_full`, so the
cross-sub-query fusion fix (#5) was never exercised. The run's retrieval quality reflects
the max-merge this review replaced, not the sum-merge that shipped.

### 2. `alembic upgrade head` had not been run

The `reasoning` column from PR #102's migration was missing. Applied before the run
(`7c3e9a1f5b2d → 9f2a7c1d4e83`). Nothing in the pipeline reads it, so the run was
unaffected — but `MetricsRepository`'s three read methods would still have raised
`UndefinedColumn`.

---

## What the run actually verified

- [x] **#2 — `as_of` reaches the fundamentals leg.** `[fundamentals] running for FIG as of 2026-09-13`. The node receives the date and passes it; previously it never saw one.
- [x] **#2 — the historical-run caveat stays quiet on a current run.** `as_of == today`, and no "prior knowledge is not bounded" gap appears. The caveat logic fires on date, not unconditionally.
- [x] **#8 — cost-log rotation.** All 45 lines went to the new `docs/cost-log-2026-09.jsonl`; the 1.0 MB `cost-log.jsonl` was untouched.
- [x] **#8 — disk reconciliation still finds a run across the rotation.** `cost_ledger_gap_usd = $0.00`, `n_events = 44`, matching state exactly.
- [x] **#9 — the shared `structured_call` module.** 39 forced tool calls (6 debate turns, 27 risk turns, 3 research-manager, 3 risk-judge) across all three refactored ports. **Zero** schema violations, zero retries, zero errors.
- [x] **#6 / #7 — config and dead-code removal.** CLI and server both start and run clean with the dead modules gone and `require_env` on every required setting.
- [x] **Verdict-consistency guard (#100) is correctly silent.** Executive Summary and Assessment section both say `INSUFFICIENT_EVIDENCE`, and item 10(a) is a genuine Data Gap, which is what forces that verdict. No false flag.
- [x] **#103 — `/latest-filings` date bound**, verified against live EDGAR after the restart (above). No LLM spend.

## What the run did NOT verify

- [ ] **#4 — the forced-memo prefix-cache fix.** The agent finished naturally in **10 turns of 45**, so the forced-memo path never executed. The fundamentals loop showed 85.6% cache-read on 28,630 uncached input tokens — squarely inside the 49.5–88% / 22–32k baseline band, i.e. unchanged, because the changed code did not run. Needs a run that hits `MAX_TURNS` or the budget stop.
- [ ] **#5 — cross-sub-query RRF fusion.** Ran against the stale server (see above). Unexercised.
- [ ] **#2 — the `filed_before` bound on `ask_edgar`.** `as_of` was today, so the bound is a no-op by construction. Needs a `--as-of` in the past.
- [ ] **#3 / #10 — eval harness mode and `use_hybrid`.** Not part of a pipeline run.
- [ ] **#11 — the three silent failures.** No vendor failure, no empty completion, and `--test` is not on the pipeline path. Unit-tested only.
- [ ] **#1 — `extract-metrics`.** Not part of the pipeline; covered by `tests/test_cli_commands.py`.

---

## Fixes applied during this check

- [x] Applied the pending migration: `uv run alembic upgrade head` (`9f2a7c1d4e83`, adds `financial_metrics.reasoning`)
- [x] Restarted the API server so it serves current code
- [ ] **Add a version probe so a stale server cannot go unnoticed.** This failure was silent and cost a whole run's worth of verification. `/corpus-status` (or a `/health`) should report the running code's git SHA, and the trading CLI should warn when it differs from the working tree.
- [ ] **Make `/ask` and `/latest-filings` reject unknown request fields** (`model_config = ConfigDict(extra="forbid")`). A bound the client sends and the server silently discards is the exact failure above, and it would have surfaced as a 422 on the first call instead of a wrong answer 30 calls later.

## Observation worth acting on separately

The single largest cost in the run is **not** the agent loop:

| line | tokens in | cache read | cost | share of run |
|---|---|---|---|---|
| `trading-fundamentals` (agent loop) | 28,630 | 169,707 (85.6%) | $0.0168 | 11% |
| `trading-fundamentals-tools` (30 × `/ask`, deepseek) | **172,336** | 4,864 (**2.7%**) | **$0.0889** | **56%** |

The server-side answer calls are 56% of the run and essentially uncached — each `/ask`
sends 8 fresh chunks (~5,700 tokens) behind a ~300-token cacheable system prompt, so
prefix caching has almost nothing to bite on. #4 improved the other 11%. If run cost
becomes a target again, this is where the money is — but note `ASK_EDGAR_K = 5` was
already tried and reverted on retrieval-coverage grounds (`app/agent/tools.py`), so it
is not a free win.

---

## Recommended next step

Re-run FIG against the restarted server, and with `--as-of` in the past, so that #5's
fusion and #2's retrieval bound are both actually exercised. Roughly $0.16 and ~5
minutes. The run above is a clean regression check; it is not yet evidence that
retrieval improved.
