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

### D15. Collapse repeated footnotes to their newest copy, kept
- **Found by:** an ACN research run (2026-10-17) said the July 2026 notes had no disclosed use of proceeds. The FY2026 10-K states it ("...commercial paper borrowing and funding acquisitions"). Re-asking through `/ask` reproduced the miss. The chunk ranked 9th in hybrid, and five of the top 8 slots held the October 2024 wording of the same footnote, restated in the FY2025 10-K and three 10-Qs.
- **Gold first:** added `acn-debt-use-of-proceeds` (the agent's own question). The 49-question baseline is hybrid hit@1 0.47, hit@5 0.80, hit@8 0.92, MRR 0.61.
- **Change:** after fusing the full candidate pool, a chunk whose word set has Jaccard >= 0.6 with a higher-ranked chunk from another filing counts as a repeat. A newer copy takes the older copy's slot; an older copy is dropped. Chunks from the same filing are never collapsed, because overlapping neighbours share text.
- **Threshold sweep (scratch):** 0.5 and 0.6 tied on hit@8 0.94 and MRR 0.63; 0.7 and 0.8 left the target at 7-8; 0.9 did not reach it. No question got worse at any threshold. Chose 0.6, the highest threshold that ranks the target first.
- **Result:** hit@1 0.47 to 0.49, hit@5 0.80 to 0.86, hit@8 0.92 to 0.94, MRR 0.61 to 0.63. Six questions moved up, all ACN; none moved down. The target went from 9 to 1. Live `/ask` now returns the correct use of proceeds.
- **Open items:** only ACN moved. AVGO and ASML have fewer repeated quarterlies in the corpus, so the rule is untested on them. Year-comparison tables did not collapse at 0.6, but the gold set covers few of them.

### D16. Synonym map for the keyword query, kept
- **Chose:** append general SEC vocabulary to the keyword query when a question uses an analyst term (`synonyms.py`: supply chain, contingent liabilities, buybacks, customer concentration, capital intensity, EBITDA, pricing power, moat). The keyword query ORs its terms, so additions only widen the match. The vector query is unchanged, so no extra embedding cost.
- **Guard against fitting the gold set:** first trial phrases were copied from the answers (ASML 38 to 1); the shipped map uses general filing wording instead and was measured as written.
- **Keyword only (free):** 6 of 49 questions are expanded. contingent liabilities 50 to 7, AVGO buybacks 19 to 5, ACN buybacks 9 to 4, ASML buyback 3 to 1, ASML customer concentration 38 to 1, supplier dependence stays 1.
- **Hybrid (one embedding call, same vectors before and after):** before matched the D15 baseline exactly. hit@1 0.49 flat, hit@5 0.86 to 0.92, hit@8 0.94 to 0.98, MRR 0.63 to 0.64. `avgo-contingent-liabilities` 13 to 3, `asml-customer-concentration` 16 to 5, `avgo-buybacks` 6 to 3; `acn-buybacks` 2 to 3.
- **Open items:** the decomposer still sends these terms to an LLM "expand" rewrite (`_VOCABULARY_MISMATCH_TERMS`), which once moved `avgo-supplier-dependence` from 1 to 10; not changed here. Four vocab questions is a small sample.

### D17. Overlap never carries table rows, kept
- **Found:** the chunker already repeats a split table's caption and year headings on every piece. The headerless rows came from the 80-token overlap: when a chunk ended inside or just after a table, its token tail opened the next chunk with rows and no headings. ASML's 2025 20-F chunk 3435 opened with "(2,083.1) | (1,631.2)" and the free cash flow row; the known capex failure read EUR 2.1B, which is 2,083.1.
- **Measured (free, re-chunking stored sections):** 263 of 2,402 follow-on chunks opened with carried table rows (ACN 119, AVGO 67, ASML 77). The replay of the old chunker matched the stored chunks exactly.
- **Change:** `_carry_overlap` carries the previous chunk's trailing prose paragraphs only, stopping at the last table. Re-chunked: 0 headerless openings (23 detector hits remain, all split-table pieces or new tables with their own headings).
- **Corpus:** all 19 filings reparsed and re-embedded (about $0.03); 2,553 to 2,525 chunks. Chunks whose text did not change kept their vectors (cosine 0.996 or more).
- **Retrieval (same question vectors before and after):** hit@1 0.49 to 0.47, hit@5 0.92 flat, hit@8 0.98 to 0.96, MRR 0.64 to 0.62. Eight questions up, eight down; `acn-rpo-and-cash` 6 to 9 leaves the top 8. The answer-text metric cannot see the wrong-column failure this fixes.
- **Biggest drop explained:** `acn-debt-use-of-proceeds` 1 to 5. The FY2025 and FY2026 copies of the debt footnote now overlap at Jaccard 0.558, under D15's 0.6, so the older copy is no longer collapsed and takes rank 1.
- **Decision (user):** keep, then retune the repeat threshold on the new chunks as its own change.

### D18. Repeat threshold 0.6 to 0.55, kept
- **Why:** after D17 the FY2025 and FY2026 copies of the ACN debt footnote overlap at Jaccard 0.558, so 0.6 no longer collapses them.
- **Sweep (free, same question vectors, D17 chunks):** 0.4 and 0.45 gave hit@5 0.94, hit@8 1.00, MRR 0.63, target at 3. 0.5 gave hit@8 1.00, target at 3. 0.55 gave hit@1 0.49, hit@5 0.92, hit@8 1.00, MRR 0.64, target at 1. No question got worse than at 0.6 at any of these.
- **Chose 0.55:** the D15 rule, the highest threshold that ranks the target first. Against 0.6: `acn-debt-use-of-proceeds` 5 to 1, `acn-notes-offering-after-period-end` 4 to 3, `acn-new-debt-vague` 9 to 7, `acn-rpo-and-cash` 9 to 8.
- **Caution:** the target pair clears 0.55 by 0.008, so another boundary change could undo it. 0.45 has more margin and better hit@5 but ranks the target 3rd.

### D19. Compound questions measured on real agent calls, no splitter built
- **Still happens:** the `ask_edgar` description says ONE QUESTION PER CALL (PR #97), yet 442 of 2,694 agent calls in 42 vault provenance files since 2026-09-12 join two or more asks.
- **Proxy said yes (20 hand-split ACN/AVGO questions):** 11 of 46 parts had none of their own top-3 chunks in the compound question's top 8. But a part's best chunk is not the only chunk that answers it.
- **Answer text said mostly no.** Four of those questions added verbatim to the gold set (one statement figure per part, `require: all`). Hybrid rank of the full answer, whole question vs parts retrieved separately and interleaved:

  | Question | whole | split |
  |---|---|---|
  | `acn-sbc-and-revenue-agent` | 8 | 11 |
  | `acn-opinc-and-debt-agent` | missed | 7 |
  | `acn-netinc-and-opcash-agent` | 1 | 8 |
  | `avgo-fy23-revenue-and-net-income-agent` | 2 | 2 |

- **Decision:** no splitter. Splitting fixed one and hurt two, the same pattern as PR #175. The one miss is the most instruction-laden question ("Retrieve the exact operating income figures and debt figures needed, without summing segment results"), which fits the earlier finding that boilerplate in a question dilutes its embedding.
- **Gold set:** 53 questions. Hybrid hit@1 0.47, hit@5 0.89, hit@8 0.98, MRR 0.63; multi_part (9) hit@8 0.89, MRR 0.32. Cost under $0.001.

### D20. Instruction text in agent questions measured, no stripping built
- **Seen:** 1,033 of 2,694 agent `ask_edgar` questions carry an imperative sentence after the opening clause; 90 ACN/AVGO questions end in an answer-format instruction ("Quote the exact figures.").
- **One-question probe (`acn-opinc-and-debt-agent`):** dropping its last sentence moved operating income 8 to 1 but debt stayed missed. Debt ranked 3 only when asked directly ("what was total debt?") instead of as "did total debt divided by operating income rise or fall". The miss is the ratio phrasing, not the instruction.
- **Gold first:** eight of those questions added verbatim, tag `instructed`. Prototype rule: drop trailing format sentences whose words add nothing beyond the rest of the question, plus "without ..." clauses. Hybrid ranks, original vs stripped: `acn-revenues-3yr-instructed` 3 to 1, `avgo-capex-3yr-instructed` missed to 10, `acn-sbc-revenue-instructed` 6 to 8; three unchanged, three had nothing to strip; the known miss stayed missed. hit@8 6 of 9 either way.
- **Decision:** no stripping. One better, one worse, no change at k=8.
- **Found instead:** two new plain-hybrid misses, `avgo-capex-3yr-instructed` and `avgo-opinc-3yr-instructed` (three-year AVGO statement lines).
- **Gold set:** 61 questions. Hybrid hit@1 0.44, hit@5 0.85, hit@8 0.95, MRR 0.60; instructed (8) hit@8 0.75. Cost under $0.0002.

### D21. Parser keeps text that shares a block with a table, kept
- **Found:** `avgo-capex-3yr-instructed` and `avgo-opinc-3yr-instructed` (D20) missed because AVGO's statement chunks carried no title. The 10-K writes `<div><span>CONSOLIDATED STATEMENTS OF CASH FLOWS</span><table>...</table></div>`; the flattener emitted only leaf blocks, so a div holding a table was skipped and its span never emitted.
- **Measured (free, all 19 corpus filings):** 183 such strings, 170 before the nested block (statement and note titles, table captions, ACN's balance-sheet date line "August 31, 2025 and 2024") and 13 after it (all boilerplate such as "Amounts in table may not total due to rounding.").
- **Change:** a non-leaf block emits the text it holds before its first nested block. Text after it is still dropped, since emitting it there would put it ahead of the table. Old vs new parse: section structure identical in all 19 filings; AVGO gains 770-1,400 characters per filing, ACN 26, ASML 306.
- **Corpus:** the 9 filings with added text reparsed and re-embedded (about $0.02).
- **Result (61 questions, same question vectors):** hit@1 0.44 to 0.46, hit@5 0.85 to 0.84, hit@8 0.95 to 0.98, MRR 0.60 to 0.61. `avgo-opinc-3yr-instructed` missed to 4, `avgo-capex-3yr-instructed` missed to 8, `avgo-capex-fy25-instructed` 5 to 1, `acn-cash-fy25` and `acn-total-assets-fy25` 4 to 3. Down, all still in the top 8: `avgo-auditor` 5 to 6, `avgo-auditor-and-icfr` 5 to 6, `avgo-buybacks` 3 to 5, `avgo-fy23-revenue-and-net-income-agent` 2 to 3.

## Still open

- One miss at k=8: `acn-opinc-and-debt-agent` (debt asked as a ratio, D19/D20). `avgo-capex-3yr-instructed` sits at the edge (8). Weakest hits: `acn-rpo-and-cash` and `acn-sbc-and-revenue-agent` (8).
- Wrong-fiscal-year columns are not measured: the answer-text check can't see them. D17 removed the headerless fragments that cause them, but no gold entry tests the column.
