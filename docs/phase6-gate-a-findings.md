# Phase 6 Gate A — debate claim graph probe

`scripts/probe_debate_graph.py` implements the two checks the Phase 6 plan's
Gate A asks for: `distinct_ids / claims` (does the model reuse `claim_id`s?)
and `rebuts_resolved / rebuts_total` (does `rebuts` point at real opposing
claims, or dangle?). It reads `debate_turns` out of a live LangGraph
checkpoint by thread id.

**Live checkpoints for the five termination-criterion runs (AVGO, ACN, FIG,
ASML, MSFT) are gone.** The two plain-named threads still in
`TRADING_CHECKPOINT_DB_URI` (`trading-FIG`, `trading-MSFT`) both pre-date the
Phase 5 debate cycle — their `channel_values` carry `debate_summary`, the old
overwrite-channel field, not `debate_turns`. (`debate_nodes.py`'s module
docstring already says as much: "Existing pre-Phase-5 threads are
unresumable... use a fresh --thread-id.") The Postgres instance has been
reused for other test threads since, and the five runs' checkpoints were not
preserved.

That leaves `trading-agent-known-gaps.md` §"Phase 5" item 4 as the record of
this measurement, and it is **more rigorous** than what the probe script
computes, not less: it checked, for all 145 claims across all five
transcripts, whether every `rebuts` id resolves to a claim made in the
opponent's **immediately preceding turn specifically** — not merely some
earlier opposing claim, which is the looser thing the generic probe checks.

**Result (measured 2026-08-24, against the raw saved transcripts):**

| metric | value |
|---|---|
| claims | 145 |
| distinct `claim_id`s | 145 (**0% reuse**) |
| `rebuts` resolving to the immediately-preceding opposing turn | 95/95 (**100%**) |
| turns with empty `rebuts` | 0% |
| concessions across 30 turns | **0** |

## Reading against the Gate A decision table

The Phase 6 plan's table keys off `rebuts_resolved / rebuts_total`:

- **> 0.8** → "the debate graph is connected; `rebuts` is a real contestation
  signal." **This is what was measured (100%).** The synthesizer can
  index-join on `rebuts` edges; a `contested_claims`-style summary (§7 of the
  Phase 6 plan, in spirit — though risk's ledger builds contestation from
  ledger `severity_spread`/`likelihood_spread`, not `rebuts`, since risk
  scores are numeric and don't need the debate's text-rebuttal mechanism) is
  trustworthy where it's built from real data.

The plan's own risk note reads a high ratio as a reason the free-form-id
approach might already be "working better than the 145/145 statistic
suggests," making a Python-owned slate over-engineering. **That inference
doesn't hold once the two numbers are looked at together, and the reason is
mechanical, not a matter of taste:**

- `rebuts` and `claim_id` reuse are different tasks. `rebuts` asks the model
  to **point at** something that already exists (a specific opponent
  `claim_id`, supplied in the immediately-prior turn's own text, still in
  context) — a lookup, and the model is measurably good at it (100%).
- The risk panel's ledger requires the model to **use the same handle** for
  a return visit to one concept, days (turns) after it first appeared,
  without it being reprinted verbatim nearby — restatement, not lookup.
  `claim_id` reuse is exactly this second task, and it happened **zero times
  in 145 opportunities** across five full runs.

A well-connected `rebuts` graph is evidence the model tracks *what was just
said*. It is not evidence about whether it can hold a stable identifier for
a concept across a multi-turn scoring exercise — the debate never asked it
to, since nothing in Phase 5 required two turns to agree on what a
`claim_id` refers to the way three risk personas scoring one ledger would.

**Conclusion: Gate A does not invalidate §2's design decision.** The
Python-assigned factor slate (`domain/risk.py`, `RiskFactor.factor_id`
`default=""` with Python filling it in `_assemble`) stands: it targets
exactly the failure mode the 145/145 statistic demonstrates (id reuse does
not happen on its own), while the rebuts-based contestation mechanism the
plan flags as a reason to reconsider addresses a different, unrelated task
the model already does well. Also confirmed: **0 concessions across 30
turns** means the `concession_trigger` machinery is inert in this setup, as
the plan predicted — it is correctly absent from `RiskTurnPayload` (no
concede/sharpen/hold stance field; the risk panel scores factors, it does
not negotiate a verdict).

## Re-running

```
uv run python -m scripts.probe_debate_graph <thread-id> [<thread-id> ...]
```

Useful again once real `risk_turns` checkpoints exist — the same
lookup-vs-restatement question applies to whether risk-panel `factor_id`s
proposed in turn 0 actually get scored under the same id in turns 1–2, which
`build_risk_ledger`'s adversarial fixtures (§9.2) test directly, but a live
probe is a cheap second check once real runs exist.
