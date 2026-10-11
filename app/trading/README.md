# Trading

A multi-agent pipeline that turns one ticker into a decision memo. Fundamentals, technical and
news analysts run in parallel, a bull/bear debate and a risk panel follow, and synthesis
writes the verdict. Glossary: [CONTEXT.md](./CONTEXT.md). Code walkthrough: [docs/tutorial.md](../../docs/tutorial.md).

Run everything from the repo root, after the setup in the [root README](../../README.md#setup).

## Before a run

- **EDGAR Research's API server must be up.** The fundamentals analyst runs the Research agent,
  whose tools call it at `http://localhost:8000`:
  ```bash
  uv run uvicorn app.main:app --reload
  ```
  Not needed with `--only technical --only news`, or with `MOCK_FUNDAMENTALS=1` when a cached
  fundamentals report exists for that ticker and date (without one, the real agent runs).
- **Postgres** holds the run's checkpoints (`TRADING_CHECKPOINT_DB_URI`).
- **`FINNHUB_API_KEY`** feeds the news leg.

## CLI: `python -m app.trading.interface.cli`

```bash
uv run python -m app.trading.interface.cli AVGO --as-of 2026-08-29 --max-usd 0.75
uv run python -m app.trading.interface.cli AVGO --only technical --only news   # no fundamentals
```

| Flag | Meaning |
|---|---|
| `TICKER` | Required. |
| `--as-of DATE` | Analysis date. Filings, prices and news are bounded at or before it. Defaults to today. |
| `--only ANALYST` | Run only `fundamentals`, `technical` or `news`; repeat to pick several. Synthesis still runs and records the rest as data gaps. |
| `--max-usd FLOAT` | Hard per-run cost cap. Default `0.75`. |
| `--wall-clock-timeout-s FLOAT` | Hard per-run deadline in seconds. Default `1800`. |
| `--thread-id ID` | Checkpoint thread. Defaults to `trading-<TICKER>`; an `--only` subset gets its own suffix. |

**Re-running a thread resumes it.**
- **Interrupted thread:** it continues from its checkpoint, with the budget and deadline it
  started with. The flags on the new command line don't change them. The deadline is an
  absolute instant fixed at the first start, and a resume whose deadline has already passed
  is refused: the run-level guards only fire between nodes, so it would otherwise pay for the
  whole fundamentals stage and then abort with no memo.
- **Finished thread:** it returns the stored result without spending.
- **To start over** or change the budget, use a new `--thread-id`.

**Output:**
- The decision memo as JSON on stdout.
- Markdown artifacts in a dated vault folder under `$HOME/$MEMO_DIR`: the fundamentals memo,
  technical, sentiment, debate and risk reports, and the decision memo.
- One `run_summary` line in `docs/cost-log.jsonl`.

## HTTP API: `POST /trading/analyze`

Served by [interface/api.py](./interface/api.py), mounted by `app/main.py` on the same server
as EDGAR Research. It runs exactly what the CLI runs, with the same lifecycle code.

```bash
curl -s --max-time 2000 localhost:8000/trading/analyze -H 'Content-Type: application/json' -d '{
  "ticker": "AVGO", "as_of_date": "2026-08-29", "max_usd": 0.75, "wall_clock_timeout_s": 1800
}'
```

| Field | Default | Meaning |
|---|---|---|
| `ticker` | required | |
| `as_of_date` | today | Same as `--as-of`. |
| `max_usd` | `0.75` | Same as `--max-usd`. Must be > 0. |
| `wall_clock_timeout_s` | `1800` | Same as `--wall-clock-timeout-s`. Must be > 0. |
| `thread_id` | `trading-<TICKER>` | Same as `--thread-id`. |

- **It blocks for the whole run**, which takes minutes, so give the client a long timeout.
- **API key:** if `APP_API_KEY` is set, send it as an `X-API-Key` header.
- **Unknown fields** are a 422.

**Response:** `{ticker, thread_id, status, decision_memo, run_terminated_by}`.

| `status` | Meaning |
|---|---|
| `started` | A new run on a fresh thread. |
| `resumed` | An interrupted thread continued from its checkpoint. |
| `completed` | The thread had already finished; the stored result is returned without spending. |

- `decision_memo` is `null` when the budget or deadline stopped the run before synthesis.
  `run_terminated_by` then says which one stopped it.
- A resume refused for a passed deadline returns **409**.
- The vault artifacts are written as for the CLI, without the terminal log.

## Scripts: `python -m scripts.<name>`

Validation batteries and probes from the phase work, in `scripts/` at the repo root. Most run
the real pipeline, or part of it, and spend; check the cap flags before running one.

| Script | What it is for |
|---|---|
| `run_p9_battery --as-of DATE [--tickers …] [--suffix -r2] [--max-usd 0.75]` | Run the watchlist battery one ticker at a time, writing a manifest as it goes. Checks first that the API server is up. |
| `p9_automated_gate MANIFEST` | Every machine-checkable exit criterion over a battery's manifest, before the manual audit. |
| `build_audit_worksheet MEMO… --out-dir DIR` | Pull the claims a human must check out of memos into a fixed CSV. |
| `rebuild_manifest_from_disk MANIFEST --tickers …` | Rebuild lost manifest rows from the vault, cost log and checkpoints. |
| `criterion8_stability --as-of DATE [--tickers AVGO NFLX]` | Re-run battery tickers on fresh threads; does the verdict direction hold? |
| `discrimination_probe --arm distressed\|exceptional [--tickers MSFT ACN]` | Swap in a manipulated fundamentals report; does the verdict respond to the evidence? |
| `risk_determinism_check TICKER [--as-of DATE]` | Does the risk stage give the same verdict on a replayed debate, at temperature 0 and at production settings? |
| `fixed_ledger_judge_repeat TICKER [--as-of DATE] [-n 3]` | Does the Risk Judge alone vary on a byte-identical risk ledger? |
| `localize_risk_variance TICKER [--as-of DATE] [--max-turns 9]` | Find the first risk-panel turn where an identical prompt gives a different output. |
| `probe_debate_graph THREAD_ID…` | Measure claim-id reuse in checkpointed bull/bear debates, e.g. `trading-FIG`. |

```bash
uv run python -m scripts.run_p9_battery --as-of 2026-08-29 --tickers AVGO NFLX
```
