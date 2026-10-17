# Retrieval decision log

Every decision taken while measuring and improving EDGAR retrieval, in order, with
what it was based on and how it turned out. All on 2026-10-17. The numbers behind each
entry are in `retrieval-improvement-checklist.md`.

Metric throughout: hybrid hit@8 on the gold set, run with `eval_retrieval` (k=8 is what
the answer model sees).

## Working rules

| Rule | Why |
|---|---|
| Measure before changing anything | No accuracy number existed: the old eval harness was removed and its test set never committed. |
| Score by answer text, never chunk ids | Chunk ids change on every re-ingest, and id-based gold once inverted a verdict. |
| Ask before every paid call, with its cost | Standing rule. Every embedding and LLM run here was approved first; total spend about $0.07. |
| Judge on plain hybrid, which is deterministic | The decomposer's output varies between identical runs (D9). |
| Don't tune toward the gold set | 37 questions on two tickers: a heuristic fitted to them proves nothing. A failed change was closed, not adjusted. |
| One stacked PR per change | Each change can be reviewed, kept or closed on its own. |

## Decisions

### D1. Build the measuring stick first
- **Options:** start on a likely fix (reranker, table headers) or build an eval first.
- **Chose:** P0 gold set and runner (PR #172) at the top of the checklist.
- **Why:** every later item needs a before/after number.

### D2. Gold-set design
- **Chose:** answer strings with `require: any|all`; ticker, form and filing-date filters so FY2025 and FY2026 filings can't be confused; questions taken from what the research agent actually asked; `--check-gold` verifies every answer string by SQL, at no cost.
- **Constraint:** the local corpus only holds ACN and AVGO, so every question is about them.

### D3. Runner scope
- **Chose:** score vector, keyword and hybrid side by side; embeddings only by default; decomposer left out at first.
- **Why:** keeps each run under a cent and deterministic; shows which path finds what.
- **Accepted:** hybrid fuses `3 * depth` candidates, so ranks beyond 8 can differ slightly from production.

### D4. Grow the set even though the score dropped
- **What happened:** 15 to 30 questions moved hybrid hit@8 from 0.87 to 0.80.
- **Chose:** accept the lower number as the more honest one.

### D5. Inspect misses before blaming retrieval
- **What happened:** two questions missed in every mode.
- **Found:** `acn-buybacks` was a gold defect (it accepted only the equity-statement label while the cash-flow line and Item 5 also answer it). `acn-cash-fy25` was half gold, half real.
- **Chose:** fix the first; split the second into a strict table entry and a prose entry.
- **Rule adopted:** list every chunk that answers a question and accept all of them before calling it a miss.

### D6. First improvement: filing-date hints (PR #173), kept
- **Options:** date hints, a `--decompose` flag, or the chunk prefix.
- **Chose:** date hints. No re-ingest cost, and they target the weakest tag (8-K, hit@8 0.50).
- **Design decisions:**
  - Read only "after/since <date>" and "in/during <Month YYYY>"; period-end dates ("as of", "ended") are not filing dates.
  - A hint may only narrow. `filed_before` is the run's look-ahead guard and can never move later.
  - A window that matches nothing is retried without the hint.
- **Result:** 0.84 to 0.87; one question moved (9 to 5), no others changed. Matched the prediction made before the run.

### D7. Measure the decomposer before changing it (PR #174)
- **Chose:** add `--decompose`, which scores the production path.
- **Found:** a wash (hit@8 0.87 vs 0.84). The regex fires on 15 of 31 questions, mostly on "compared with". Three of the four multi-part questions never trip it.

### D8. Compound-question trigger (PR #175), closed
- **Options offered:** tighten the regex, protect expansions, or trigger on "X and Y".
- **Chose:** "X and Y", because it targeted the group with no rank-1 hits.
- **Result:** all three targeted questions got worse or stayed missed (multi-part 0.75 to 0.50).
- **Decision:** close it rather than adjust the concept list toward the gold.
- **Learned:** `acn-rpo-and-cash` was blocked by the balance-sheet chunk, not by decomposition.

### D9. Treat decomposer runs as noisy
- **Found:** questions whose rewrite path didn't change still moved up to 11 ranks between runs.
- **Chose:** compare only the questions a change targets, repeat before claiming a decomposer gain, judge everything else on plain hybrid. Saved as a memory.
- **Consequence:** the earlier "4 better, 3 worse" reading of D7 was partly noise.

### D10. Contextual chunk prefix (PR #176), reverted
- **Chose:** prepend ticker, form, filed date and section to each chunk's embedding text; re-embed both tickers as a trial.
- **Result:** hit@8 unchanged (0.87); hit@1 0.45 to 0.39. The target chunk was still missed.
- **Decision:** revert. The live database was re-embedded from plain content (`main` still embedded plain text, so keeping trial vectors would mix two kinds), and #176 was closed. The record was moved to #174 so it wasn't lost with the PR.

### D11. Diagnose before a third fix
- **Chose:** look at what outranks the balance-sheet chunk instead of trying another change.
- **Found:** the chunk ranks 111 of 359 for its own question, though its vector is coherent (0.995 to the other ACN balance sheets).
- **Experiment:** stripping the numbers barely helped (rank 97); five rows ranked 55; one row with its title ranked 1.
- **Deferred:** a row index. It needs a new table, an ingestion step and a retrieval merge.

### D12. Test the pattern on more tables before building
- **Chose:** add six balance-sheet questions (37 total) and repeat the row test.
- **Found:** the problem was specific to ACN's 45-row chunk. AVGO's balance sheet already ranked 1-2, and ACN goodwill and debt were answered by their notes at rank 1.
- **Decision:** don't build the row index; it would fix one of two real misses.
- **Spotted:** a confound. The AVGO chunk says "BROADCOM INC."; the ACN chunk never says "Accenture". The failed prefix used the ticker.

### D13. Isolate the lever
- **Chose:** test the company name alone, then name plus title.
- **Found:** "Accenture plc" alone moved the chunk from 111 to 8 (cash) and 152 to 1 (total assets). The ticker gave 86.
- **Caution kept:** one chunk re-embedded against an unchanged pool is an upper bound.

### D14. Full trial with the company name (PR #177), kept
- **Root cause found on the way:** securities were stored with the ticker as their name. The resolver now reads SEC's company title and ingestion stores it.
- **Result:** hit@8 0.86 to 0.95. Three misses entered the top 8 (at ranks 7-8); 10 questions up, 5 down by 1-2 ranks; hit@1 0.49 to 0.46.
- **Decision (user):** keep. The live database already holds these vectors.
- **Open items:** the gains sit at the edge of k=8; six of the 37 questions were added for this problem; the ingestion path is not yet exercised live.

## Still open

- Merge order: #172, #173, #174, #177. Until #177 merges, ingesting from `main` would mix plain and named vectors.
- After merging, ingest one ticker to exercise `_embed` with the stored name.
- Remaining misses: `avgo-contingent-liabilities` (vocabulary) and `acn-new-debt-vague` (an 8-K question with no date).
- Wrong-fiscal-year columns are not measured: the answer-text check can't see them, and ASML is not in the local corpus.
