# Phase 4 — News/Sentiment Analyst: Implementation Guide (as built)

**Status: implemented, merged, and running.** This is the original planning guide amended to match the code. Every signature, constant and figure below was read from the working tree or measured on a live run, not recalled.

Amendments are marked **[AMENDED]** where the code diverged from the plan, and **[NEW]** where the code grew something the plan never anticipated. Where the plan was right, it is left standing — most of it was.

The original provenance caveat ("treat every signature as a diff target") is retired: the signatures here *are* the code.

---

## The two decisions that mattered most

Both held up. One needed widening.

**1. `as_of_date` lives in `TradingState`, never computed inside a node.**

Correct, and load-bearing. **[AMENDED]** the rule turned out to need enforcing in more than one place: `synthesizer_node` was calling `date.today()` to stamp `data_as_of_date`, so a `--as-of 2025-03-01` run produced a memo claiming to be current as of today while describing a window from months earlier. Nothing caught it, because the memo looked plausible. Fixed by reading `state["as_of_date"]` and refusing to run without it.

The generalised rule, worth stating in the guide rather than leaving implicit: **any node that stamps a date is subject to this, not just the ones that fetch.** `date.today()` appears exactly once in the codebase, at the CLI boundary.

**2. Only judgments come from the LLM; metadata is carried through in Python.**

Correct, and it paid for itself. **[AMENDED]** the plan said "only `summary` and `sentiment`". There are now **three** LLM-generated fields — `summary`, `sentiment`, `relevance` — and the principle is better stated as: *the model returns only judgments about an article, never any fact about it.* Headline, date, source and URL are still joined by integer index and never retyped.

Live confirmation this was the right call: in one run the model returned `"index": "[0]"` — echoing the prompt's own `[N]` marker — and three articles were dropped. The join surfaced the loss instead of silently shortening the digest, which is exactly what the index design is for. (The fix was to accept the bracketed form; see §4.)

---

## 0. Scope: one node or two?

Held. Two nodes: `news_node` does fetch → bound → dedup → digest; `sentiment_node` is deterministic aggregation with zero LLM calls.

**[AMENDED]** three details:

- `sentiment_node` is `async def`, not `def` — every node in the graph is async, and mixing the two buys nothing.
- It is no longer a ~30-line pure function. It filters by relevance (§1) and carries a stale-checkpoint guard (§5). Still zero LLM calls, still zero network.
- The deferral of social sentiment (Reddit/StockTwits) was correct: **Phase 5's debate shipped without it** and did not need it.

---

## 1. Domain types

`app/agent/trading/domain/news_digest.py`

**[AMENDED]** two fields were added after live measurement showed the original schema could not express something true.

```python
Sentiment = Literal["positive", "negative", "neutral"]

# [NEW] How much an article is actually about the ticker under analysis.
Relevance = Literal["primary", "mentioned", "unrelated"]

# [NEW] Which relevance levels the sentiment aggregate counts. Named rather
# than inlined so the policy is one edit, and so a test can assert against
# the same constant the node uses.
AGGREGATED_RELEVANCE: frozenset[str] = frozenset({"primary"})


class NewsItem(BaseModel):
    headline: str
    published_date: date        # UTC date, derived in Python from the unix ts
    source: str
    url: str
    summary: str                # LLM-generated
    sentiment: Sentiment        # LLM-generated, enum-constrained
    relevance: Relevance        # [NEW] LLM-generated, enum-constrained


class SentimentSummary(BaseModel):
    ticker: str
    as_of_date: date
    positive: int
    negative: int
    neutral: int
    net_score: float
    article_count: int          # articles the aggregate covers
    excluded_by_relevance: int  # [NEW] digest items dropped before aggregating
```

`NewsDigest` is unchanged from the plan.

**Why `relevance` exists** — the plan had no way to express this, and the gap was invisible until measured. Finnhub tags broad market coverage with the requested symbol. For MSFT on 2026-08-21, of the 60 articles reaching the digest, **6 named Microsoft in the headline, 9 mentioned it in passing, and 45 had no Microsoft signal at all** — Ferrari, Alibaba, Walmart, Netflix, 13F trackers. All 60 carried `related: "MSFT"`, so the vendor's own field cannot filter. Without `relevance`, `net_score` measured AI-sector sentiment and Phase 5 would have consumed it as company sentiment.

**Why `excluded_by_relevance` exists** — without it, a genuinely quiet ticker and a noisy feed filtered down to nothing both read as `article_count=0`, and those warrant very different confidence in the score.

**The coupled-commit rule held, and is stronger than stated.** The plan warned that a checkpoint written before the `ALLOWED_MSGPACK_MODULES` entry fails to deserialize on resume. **[NEW]** the observed failure mode is worse than "fails": adding a *required* field to `NewsItem` leaves old checkpoints deserializing with the outer `NewsDigest` intact and its items as **plain dicts**, raising nothing at the read. The first symptom was `AttributeError: 'dict' object has no attribute 'relevance'`, several frames from the cause. Two consequences now baked in:

- New fields on a checkpointed model get a **default**, so old checkpoints still rebuild.
- `sentiment_node` asserts its items are `NewsItem` instances and fails with a message naming the real problem.

---

## 2. Thread `as_of_date` through `TradingState`

Held exactly as written — the state field, the CLI arg with `date.today()` as the single boundary default, and the fail-loud assert in the node.

**Cross-phase flag: still open, still out of scope.** Verified against the current tree: `get_price_history(ticker)` takes no `as_of` and does not mention it anywhere. A `--as-of 2025-03-01` run gets March-2025 news beside present-day prices.

Worth stating more sharply than the plan did: **`--as-of` currently binds the news leg only.** The flag is more reassuring than it is complete, and anyone reading a probe-date memo needs to know that.

---

## 3. Finnhub news adapter

**The recalled API shape was correct.** Verified against a live response: the payload is a JSON array whose objects carry exactly `category, datetime, headline, id, image, related, source, summary, url`, with `datetime` a Unix epoch in seconds, UTC. No missing fields, no extras. The **free tier serves `/company-news`** — 247 articles for a 14-day MSFT window.

`fetch_company_news`, `_to_utc_date` and `filter_and_dedup` are as written, including the `if not ts` guard that catches both `None` and `0`. The timezone reasoning was correct and is unchanged.

### [AMENDED] `MAX_ARTICLES`: 60 → 300, and now derived from the budget

The plan set the cap at 60 as a cost floor and predicted the budget would never bind. Measurement inverted the relationship.

At 60 the cap was **discarding the evidence rather than the noise**. Of MSFT's 247 in-window articles, 58 were primarily about Microsoft — and the cap kept **6 of them**. The newest 60 articles spanned 5 days of a 14-day window and dropped an entire 101-article event day. Relevance scoring made the signal correct and left it too thin to act on.

300 is derived from `NEWS_BUDGET_USD`, not chosen for roundness. Worst case is ~$0.00042/article plus a 496-token system prompt per batch, so a full-cap run costs ~$0.136 — about 68% of the budget.

**The ordering is the point, and the plan had it backwards.** The budget assertion fires *after* the batches are paid for, so it can never refund a run it fails. Keeping the cap strictly inside the budget means volume degrades to flagged truncation instead of an exception charged at full price. So: **the cap bounds spend; the budget assertion catches model misrouting.** Neither substitutes for the other.

### [AMENDED] Dedup does not earn its keep on this feed

The plan said dedup "cuts LLM cost roughly proportionally" and stops a digest being 40% syndicated reprints. Measured on MSFT's 247 articles: **dedup removed 0.** Across Yahoo, Benzinga and SeekingAlpha the headlines differ enough that exact-headline matching never fires.

It is cheap and harmless, so it stays — but it is not a cost lever, and the plan should not have claimed it was. The cap is the lever.

---

## 4. The Haiku digest — index-join, not echo-back

`BATCH_SIZE = 15` held. The design rule held. Several mechanics changed.

### [AMENDED] The prompt must name the company

The plan's prompt never said which company the batch was about. It said *"sentiment is about the likely effect on the company's equity"* while the batch contained articles about dozens of different companies — so the model scored each article against whichever company *that article* was about. A Netflix sell-off was being recorded as a negative data point for MSFT.

The user turn now leads with `COMPANY UNDER ANALYSIS: <TICKER>`, and both relevance and sentiment are defined relative to it. This fixed sentiment attribution, not just relevance.

The model returns four fields: `index`, `summary`, `relevance`, `sentiment`.

### [AMENDED] Model id comes from config

`model="claude-haiku-4-5"` as a literal is wrong for this codebase — it must be `AGENT_MODEL` (env `LLM_CLAUDE_MODEL`), the same value `_MODEL_PRICING` is keyed on. A literal that drifts from the pricing table produces silently wrong cost logs.

### [AMENDED] `_parse_index` tolerates the bracketed form

`int(obj["index"])` was too strict. A live 3-article batch returned `"[0]"`, `"[1]"`, `"[2]"` — the model echoing the prompt's own `[N]` marker — and all three articles were dropped as unparseable. They were the three most on-topic stories in the batch.

The form is unambiguous, so it is stripped rather than rejected: a rejected index costs a real article, which is the exact data loss the join exists to prevent. Values needing guesswork are still rejected — `bool` (since `int(True) == 1` would silently claim index 1) and non-integral floats.

### [NEW] Batches run concurrently, and one bad batch does not kill the run

A full-cap run is 20 calls. They are independent, so serial execution bought nothing but latency.

- `MAX_CONCURRENT_BATCHES = 5`, via `asyncio.gather` behind a semaphore. `gather` preserves input order, so items stay newest-first.
- A batch whose reply will not parse costs **its own articles, not the run**, and records the hole in `news_digest_issues`. Only `VendorError` is caught — that is the malformed-output case; API, auth and exhausted-retry failures are systemic and still fail loudly.
- If *every* batch fails, the run raises rather than returning an empty digest, which would be indistinguishable from a quiet ticker.

Measured: 248 articles, 17 batches, **24.7s** wall clock.

### The structural-guard claim held — with one honest qualification

The plan argued a structural check (index present / in range / unique, enum valid) has no false-positive problem, unlike Phase 3's regex-over-prose guard. **That held.** The join has produced no false positives across every run.

**[NEW]** The contrast is sharper than the plan knew. In the same period, Phase 3's *numbers* guard needed three further rounds of tightening against live output — RSI band edges, a Unicode minus sign (U+2212, which `float()` also rejects), and a suspended hyphen ("the 50- and 200-day averages"). Each was a legitimate phrasing the regex had not anticipated. The lesson generalises: **prefer structural checks, and when prose must be checked, fix the prompt first and treat the regex as a backstop.**

### `build_digest` signature

```python
async def build_digest(articles, ticker) -> tuple[list[NewsItem], list[str], float | None]
```

**[AMENDED]** takes `ticker` (needed for the prompt header and the cost log) and returns the **cost**, not raw `usage` — usage is summed and logged inside.

---

## 5. Node wiring

`news_node` is as the plan wrote it, plus a progress line reporting counts and cost.

`sentiment_node` **[AMENDED]**: `async`, filters to `AGGREGATED_RELEVANCE` before counting, reports `excluded_by_relevance`, and carries the stale-checkpoint type guard from §1.

**The empty-news case held, and Phase 5 acted on the plan's warning.** The plan said the debate prompt "needs to handle 'no news in window' without treating absence as neutrality-with-evidence." It does, in two places:

- The sentiment block in the evidence pack ends with a literal sentence: *"An article_count of 0 is an absence of evidence, not neutral evidence."*
- A skipped analyst renders as `NOT RUN — do not infer anything about {name} from its absence`, rather than being omitted.

---

## 6. Cost logging

Held. No third cost path was built. `log_cost` from `researcher.py` is called with `mode="trading-news"`, usage summed across batches into **one log line per run**.

**[AMENDED]** the plan said to extract a shared helper if Phase 3 had solved it locally ("three call sites is where duplication stops being cheaper than abstraction"). Not needed — Phase 2's `log_cost` was already a shared function taking `(ticker, mode, usage)`. The third call site reused it unchanged. No abstraction was warranted.

---

## 7. The cost budget

**[AMENDED]** the per-article estimate was low. The plan projected ~$0.000315/article; measured is **$0.000402** — about 28% higher, because `relevance` adds output tokens the plan did not know about. The estimate's *method* was sound; only the field list changed.

Real figures from live runs:

| Run | Articles | Cost |
|---|---|---|
| FIG | 18 | $0.0063 |
| AVGO | 60 | $0.0242 |
| MSFT | 248 | $0.0997 |

Ten logged news runs, maximum **$0.1003**, all inside the $0.20 budget.

**"Make the cap loud" — delivered.** The plan required `truncated_by_cap=True` to surface in the memo. It now does, as a data gap declaring the digest a **SAMPLE**, with the vendor count, the kept count, and a note that coverage skews to recent days. It also surfaces in the vault sentiment report's caveats and in the CLI.

---

## 8. Exit criteria — status

All seven met.

| # | Criterion | Status |
|---|---|---|
| 1 | Point-in-time filter, planted violations | Met — includes the 23:30 UTC boundary that must be **kept** |
| 2 | Timezone determinism | Met — UTC / Singapore / LA, with an article in the 16:00–23:59 rollover band |
| 3 | Missing/zero timestamp | Met — counted, never dated 1970 |
| 4 | Batch integrity | Met, and extended: bracketed index, relevance enum, whole-batch failure |
| 5 | Empty result | Met, plus quiet-ticker vs filtered-to-nothing |
| 6 | Cost < $0.20 | Met — **[AMENDED]**, see below |
| 7 | Checkpoint round-trip | Met — Tier 1 serde + real Postgres `interrupt_after=["news"]` |

**[AMENDED] Criterion 6** was specified as a test asserting a run's logged `total_cost_usd < 0.20`. What exists is `_assert_within_budget` running in production on **every** digest, plus a unit test of its threshold logic. That is stronger than the specified test — a CI test checks one run, this checks every run — but it is not literally a test that reads the cost log. Recorded as a deliberate deviation rather than a silent one.

The plan's insistence that these be **fixture-based, not live**, was correct and vindicated: Finnhub honoured its `from`/`to` bounds on every observed run (`dropped_out_of_window = 0` every time). A live test would have exercised nothing.

---

## 9. Known gaps

| # | Gap | Status |
|---|---|---|
| 1 | Article bodies not point-in-time bounded | **Open** — unfixable without a point-in-time archive |
| 2 | Summary faithfulness unverified | **Open** — structural join proves metadata, nothing checks the one-liner |
| 3 | Truncation is a sampling bias | **Largely closed** — cap raised to 300; residual is a ticker exceeding 300 in-window |
| 4 | News is single-vendor | **Open, and now urgent** — see below |
| 5 | Phase 3 price fetch not `as_of`-bounded | **Open** — verified still unbounded |
| 6 | **[NEW]** Feed relevance | **Addressed** — see below |
| 7 | **[NEW]** Schema evolution breaks old checkpoints silently | **Closed** — defaults + type guard (§1) |

**Gap 4 is now the one worth deciding.** The plan said `VendorError` from this node "needs a decided policy in Phase 7". Phase 5 has since shipped and consumes the digest, so the decision is due earlier than expected: does a Finnhub outage halt the pipeline, or produce a memo flagged "news unavailable" and a debate told the news leg is absent? The machinery to do the latter already exists — `_not_run()` renders exactly that for a skipped analyst — so the cheap path is to catch `VendorError` in `news_node` and let the run continue with news marked unavailable. Still undecided; still worth deciding explicitly rather than discovering the default.

**Gap 6, with its own honest residual.** Relevance scoring fixed the sector-noise problem, but LLM relevance agreed with a plain "does the headline name the company" check **6/6 on MSFT and 10/10 on FIG**, with no disagreement in either direction. Under the current primary-only policy the model is not yet beating a free regex. It is free (same call), so there is no cost argument against it — but the judgment it uniquely adds lives in the `mentioned` tier, which nothing currently consumes. If Phase 5 ever wants sector context as a separate signal, that tier is where it already is.

---

## [NEW] 10. Things the plan did not anticipate

Three pieces of the shipped phase have no counterpart in the original guide.

**Vault artifacts.** Every run writes three files to `MEMO_DIR/TICKER/YYYYMMDD/`: a sentiment report (signal, coverage funnel, counted articles, excluded articles in their own table, earned caveats), the decision memo, and a **provenance file containing the run's real terminal session**. The pre-existing session log only recorded the research agent's tool calls and could not see pipeline node output at all, so `run_log.py` tees stdout and stderr into one chronological buffer.

**`--only` analyst selection.** A run can execute a subset of analyst legs. Subset runs get their own default thread id, because resuming a full run's checkpoint under a narrower graph would report an earlier run's cached reports as if this run produced them.

**Memo integration.** `ANALYST_OUTPUTS` records whether a leg ran; the memo now also records what it found. The sentiment signal becomes memo `evidence` (score, counts, window, excluded count); truncation, digest issues, thin samples, and zero-relevant-articles become `data_gaps`. Caveats are earned — a full healthy digest adds none of them.

---

## Suggested commit order — retrospective

The plan's order was right, and its risk estimate was right. Steps 1–3 (domain types, `as_of_date`, the fetch/filter) carried nearly all the correctness risk, and steps 4–6 were mechanical.

**[AMENDED]** one correction to the estimate: the plan said if the 6–8 hour estimate slipped, it should slip in steps 4–6. In practice the slip came from somewhere the plan did not model at all — **live-run discovery**. The bracketed index, the missing company name in the prompt, the feed-relevance problem, the cap starving the signal, and the Unicode minus were all found by running the thing on real data, not by writing it. None were visible from the plan or from fixtures.

The practical lesson for Phase 5 and beyond: **budget for a measurement pass after the code is green.** Fixtures prove the logic; only live output shows what the model and the vendor actually do. Keep that pass cheap — replaying one captured live output through changed code found three separate false positives at zero marginal cost.
