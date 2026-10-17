# Retrieval improvement checklist

Ranked by priority: expected accuracy gain, divided by cost and risk, with
measurement first because nothing below can be judged without it.

Status as of 2026-10-17. No standing accuracy number exists: the eval harness
was removed on 2026-10-11 and its 8-question set was never committed. The last
recorded figure is vector-only S@5 = 0.625, which predates hybrid search and
the OR-query fix.

Rule for every item: measure by answer content (does a top-k chunk contain the
answer string), never by chunk id, and rank the right chunk before changing
retrieval.

## P0. Build the measuring stick (do first)

- [ ] **Answer-content gold set**, committed to git (~40-60 questions).
  Each entry: question, ticker, filing, answer strings, shape tag.
  Seed from the ~100 real agent questions in the vault provenance files plus
  known failures (see "Known failures" below).
  Tags: numeric_table, numeric_prose, narrative, vocab_mismatch, multi_part, 8k_by_date.
- [ ] **Runner** `scripts/eval_retrieval.py`: hit@k, MRR and first-hit rank per
  tag. Embeddings only, about $0.01 per run. Print a per-tag table.
- [ ] **Record a baseline** in this file before any other change.
- [ ] **Parser sanity check** in `corpus-status`: flag filings where Item 1A, 7
  or 8 is empty or tiny. Zero API cost. It would have caught McDonald's and IBM.

## P1. High gain, low cost

- [ ] **Keep table headers with table chunks.** Confirmed failure: ASML
  figures read from the wrong fiscal-year column (FCF, capex, non-current debt).
  Keep a table in one chunk, or prepend its header row to every chunk that
  splits it. Ingestion change; needs re-chunk and re-embed. Measure on numeric_table.
- [ ] **Contextual chunk prefix.** Embed `"{ticker} {form} FY{year} > {section}: "`
  plus the chunk text, so vector search separates companies, years and sections.
  Needs a re-embed. Measure on multi_part and 8k_by_date.
- [ ] **Synonym map for analyst-to-filer vocabulary.** Deterministic and
  testable; extend `_VOCABULARY_MISMATCH_TERMS` into a real mapping
  ("supply chain" -> "third-party vendors", "contingent liabilities" ->
  "commitments and contingencies"). Measure on vocab_mismatch.

## P2. Medium gain, moderate cost

- [ ] **Rerank.** Fetch ~30 candidates, rerank with a cross-encoder, keep 8.
  Only worth building if the gold set shows the right chunk at rank 9-30.
  Check that first; do not build on a guess.
- [ ] **Split compound questions before retrieval, not only on regex signals.** (Measured 2026-10-17: 3 of the 4 multi-part gold questions never trip the regex, so the decomposer never sees them.)
  A 3-part question ranked the ICFR chunk nowhere; asked alone it ranked 1.
  The regex gate in `query_decomposer` misses compound questions with no
  trigger word.
- [x] **Filing-date hints for 8-K questions** (shipped 2026-10-17, see done log). "after <period-end>" ranked the
  ACN notes 8-K 10th, "in July 2026" ranked it 1. Extract month/year from the
  question into `filed_after` / `filed_before`.
- [ ] **Citation-verifier trend metric.** Log unverified literals per run so
  regressions show up without reading memos.

## P3. Coverage fixes (unlock specific tickers, not the average)

- [ ] **TOC-anchor parsing** for filers without "Item N." headings (McDonald's).
- [ ] **Follow exhibit references** for incorporation-by-reference filers (IBM:
  Items 7, 7A, 8 live in an Annual Report exhibit).
- [ ] **Follow submissions pagination** for prolific filers (JPM is limited to
  one 10-K today).

## P4. Only if the gold set shows a gap

- [ ] **True BM25 or IDF-weighted keyword ranking.** Already measured on 51
  queries: no better than plain `ts_rank`. Revisit only on new evidence.
- [ ] **Tune k and candidate pool** (`candidate_k = 3k`, rrf_k = 60). Rank decay
  is flat (5.1% from rank 1 to 8), so trimming k loses sections; leave alone.
- [ ] **Different embedding model.** Costs a full re-embed and a column change
  from vector(1536). Last resort.

## Known failures to seed the gold set

| Case | Symptom |
|---|---|
| ASML FY2023 FCF | read the 2022 column (EUR 7,167.5M vs actual EUR 3,247.2M) |
| ASML FY2025 capex | read the 2024 column (EUR 2.1B vs EUR 1,631.2M) |
| ASML FY2024 non-current debt | read the 2023 column |
| "supply chain risks" | zero lexical overlap with "third-party vendor dependencies" |
| ACN ICFR, asked as part of a 3-part question | ranked nowhere; ranks 1 alone |
| ACN notes-offering 8-K | ranked 10th with "after <period-end>", 1st with "in July 2026" |
| ACN Note 10 impairment answer | ranks 1 when asked directly |

## Done log

Record each shipped item here with the before/after gold-set numbers.

| Date | Item | hit@8 before | hit@8 after | Notes |
|---|---|---|---|---|
| 2026-10-17 | P0 baseline (15 questions, ACN + AVGO) | - | 0.87 hybrid | vector 0.73, keyword 0.73, hybrid 0.87. Hybrid hit@1 0.47, MRR 0.58 |
| 2026-10-17 | P0 baseline, gold set grown to 30 questions | - | 0.80 hybrid | vector 0.73, keyword 0.60, hybrid 0.80. Hybrid hit@1 0.43, MRR 0.54. Superseded by the next row: two gold entries undercounted answering chunks |
| 2026-10-17 | P0 baseline, 31 questions after gold fixes | - | 0.84 hybrid | vector 0.77, keyword 0.61, hybrid 0.84. Hybrid hit@1 0.45, MRR 0.57. Reference for later changes |
| 2026-10-17 | P2 filing-date hints (`date_hints.py`) | 0.84 hybrid | 0.87 hybrid | 8k_by_date hit@8 0.50 -> 0.75; `acn-notes-offering-after-period-end` hybrid rank 9 -> 5. No other question's rank changed. The vague 'raise new debt recently' question has no date and still ranks 15. hit@1 0.45, MRR 0.57 unchanged |
| 2026-10-17 | Measured the decomposer (`--decompose`), no retrieval change | 0.87 hybrid | 0.84 decomposed | Production path is a wash vs plain hybrid: 4 better, 3 worse, 1 lost from top 8. Multi-part still unfixed because 3 of 4 never trip the regex. Cost $0.0016 |
| 2026-10-17 | Compound-question trigger (`is_compound`, PR #175), rejected | multi_part 0.75 decomposed | multi_part 0.50 decomposed | All 3 targets worse or still missed; `acn-rpo-and-cash` is blocked by the balance-sheet table chunk, not by decomposition. Decomposer output varies run to run |
| 2026-10-17 | P1 contextual chunk prefix (PR #176) | 0.87 hybrid | 0.87 hybrid | Target `acn-cash-fy25` still missed. hit@5 0.74 -> 0.77, hit@1 0.45 -> 0.39, MRR 0.57 -> 0.54. 6 questions up, 5 down. No clear gain; reverted, vectors restored to plain content |

### Current baseline: 31 questions (2026-10-17, `eval_retrieval --depth 20`)

This is the reference for later changes. It follows two gold fixes (see "The two
misses, examined" below); the 30-question run before them scored hybrid hit@8 0.80.

All modes, ALL tags (hit@1 / hit@5 / hit@8, MRR): vector 0.35 / 0.68 / 0.77, 0.50;
keyword 0.39 / 0.61 / 0.61, 0.49; hybrid 0.45 / 0.71 / 0.84, 0.57.

Hybrid, by tag:

| Tag | n | hit@1 | hit@5 | hit@8 | MRR |
|---|---|---|---|---|---|
| numeric_prose | 5 | 0.60 | 0.80 | 1.00 | 0.69 |
| narrative | 5 | 0.40 | 0.80 | 1.00 | 0.58 |
| numeric_table | 9 | 0.67 | 0.89 | 0.89 | 0.76 |
| vocab_mismatch | 4 | 0.25 | 0.50 | 0.75 | 0.42 |
| multi_part | 4 | 0.00 | 0.50 | 0.75 | 0.13 |
| 8k_by_date | 4 | 0.50 | 0.50 | 0.50 | 0.54 |

What it shows:

- Hybrid beats both paths at hit@8 (0.84 vs 0.77 vector, 0.61 keyword). Keyword alone is weak on prose (0.60), vocabulary (0.25) and multi-part (0.25).
- Fusion can bury a vector hit: `avgo-contingent-liabilities` ranks 13 by vector, is absent from keyword, and ranks 19 fused.
- 8-K questions are the weakest tag: the vague wording ("raise new debt recently") ranks 15 hybrid, and "after May 31, 2026" ranks 9. Only wording that names the notes or the month ranks 1. Supports the filing-date item (P2).
- Multi-part: `acn-rpo-and-cash` is missed by every mode (its two answers sit in different chunks). This run does not use the decomposer, so it is a floor.
- `acn-cash-fy25` (strict statement table) is still missed by vector and hybrid, keyword rank 16. See below.

### Decomposer measured (2026-10-17, `eval_retrieval --decompose`)

Production path (`retrieve_full`) vs plain hybrid, 31 questions. The run made 15 decomposer
calls on gpt-5.6-luna: 4,310 in / 644 out tokens, $0.0016.

| | hit@1 | hit@5 | hit@8 | MRR |
|---|---|---|---|---|
| hybrid (no decomposer) | 0.45 | 0.74 | 0.87 | 0.57 |
| decomposed (production) | 0.42 | 0.71 | 0.84 | 0.55 |

- A wash overall, slightly negative. Four questions improved, three got worse, and one fell out of the top 8.
  Better: `avgo-revenue-fy25` 3 -> 1, `avgo-rpo` 2 -> 1, `avgo-revenue-and-opcash` 5 -> 3, `avgo-buybacks` 8 -> 6.
  Worse: `avgo-supplier-dependence` 1 -> 10 (an "expand" rewrite for "supply chain"), `acn-revenue-fy26` 1 -> 2, `acn-cash-fy25-prose` 1 -> 3.
- 15 of 31 questions trip the regex, mostly on "compared with"; plain numeric-table questions get an LLM rewrite they did not need. The rewrite helped some of them and hurt others, with no clear pattern at n=31.
- Multi-part is not fixed: 3 of the 4 multi-part questions never trip the regex (`acn-rpo-and-cash`, `acn-opcash-and-revenue`, `avgo-auditor-and-icfr`), so the decomposer never sees them. `acn-rpo-and-cash` stays missed.
- Open questions this raises, none acted on yet: tighten the regex so "compared with" alone does not trigger a rewrite; stop expand rewrites from displacing a first-rank original; trigger on "X and Y" compound questions. Each should be measured with `--decompose` against this table.

### Contextual chunk prefix measured (2026-10-17, PR #176)

ACN and AVGO re-embedded with `"{ticker} {form} filed {date} | {section}"` above each chunk
(1,363 chunks, about $0.014). Plain hybrid, which is deterministic:

| | hit@1 | hit@5 | hit@8 | MRR |
|---|---|---|---|---|
| hybrid before | 0.45 | 0.74 | 0.87 | 0.57 |
| hybrid with prefix | 0.39 | 0.77 | 0.87 | 0.54 |
| vector before | 0.35 | 0.68 | 0.77 | 0.50 |
| vector with prefix | 0.26 | 0.68 | 0.87 | 0.43 |

- The target was not fixed: `acn-cash-fy25` and `acn-rpo-and-cash` are still missed by every mode.
  Missing filing context is not why the balance-sheet chunk is unreachable.
- Vector recall at 8 rose (0.77 -> 0.87) but its top ranks got worse (hit@1 0.35 -> 0.26).
  The shared header seems to pull chunks of one filing closer together: more right chunks
  land somewhere in the top 8, fewer land first.
- Hybrid moved 6 questions up (avgo-auditor 4 -> 2, avgo-rpo 2 -> 1, acn-opcash-and-revenue
  8 -> 5, avgo-buybacks 8 -> 6, avgo-revenue-and-opcash 5 -> 4, avgo-auditor-and-icfr 5 -> 4) and
  5 down (avgo-icfr 1 -> 2, acn-icfr 1 -> 3, avgo-supplier-dependence 1 -> 2, avgo-repurchases-fy24
  2 -> 3, avgo-contingent-liabilities 19 -> beyond 20). hit@8 is unchanged.
- Net: no clear gain, and a cost in first-rank precision. The dense-table miss needs a
  different diagnosis (what does outrank that chunk, and why).
- Reverted the same day: PR #176 closed, ACN and AVGO re-embedded from plain content
  (about $0.014), so the corpus matches what `main` ingests.

### Compound-question trigger tried and rejected (2026-10-17, PR #175)

`is_compound()` sent questions joining two different concepts with "and" to the decomposer.
On the gold set it fired on exactly the three multi-part questions the regex missed. Result
of one `--decompose` run (18 rewrites, $0.0019):

| Question | decomposed rank before | after |
|---|---|---|
| `acn-opcash-and-revenue` | 8 | 13 |
| `avgo-auditor-and-icfr` | 5 | 8 |
| `acn-rpo-and-cash` | missed | missed |

Multi-part hybrid-decomposed hit@8 went 0.75 -> 0.50. All three targets got worse or stayed missed.

- Decomposition is not what multi-part lacks. `acn-rpo-and-cash` needs the balance-sheet chunk,
  which no mode finds even for its own single question (`acn-cash-fy25`). That is the
  dense-table problem (P1 contextual prefix), not a missing rewrite.
- Splitting the other two made them worse: summed RRF over 2-4 sub-queries spread the top
  ranks across more chunks. Sub-queries were not logged, so the exact cause is unconfirmed.
- The decomposer's output varies between identical runs. Questions whose rewrite path did
  not change moved anyway: `avgo-contingent-liabilities` 17 -> 6, `avgo-supplier-dependence`
  10 -> 12. So the decomposed column's ALL row (0.84 both times) is noise-dominated; only
  the targeted questions can be compared across one run pair, and a real claim needs repeats.
- Decision: do not merge #175. Next for multi-part is the dense-table fix, then re-measure.

### The two misses, examined (2026-10-17)

- `acn-buybacks` was mostly a gold defect. The answer string matched only the equity-statement label, but the fiscal 2025 total also sits in the cash-flow line ("Purchases of shares | (4,619,497)") and the Item 5 table (4,614,969). Keyword search already ranked an Item 5 chunk 9th. The entry now accepts both figures.
- `acn-cash-fy25` was half gold, half retrieval. The MD&A sentence "Cash and cash equivalents were $11.5 billion, compared with $5.0 billion" answers it in rounded prose and keyword ranks it 7th, but the gold only accepted the statement table. Split in two: the strict entry stays (balance-sheet chunk: keyword rank 16, vector and hybrid beyond 20), and `acn-cash-fy25-prose` accepts the MD&A sentence (keyword rank 1).
- The real finding: a dense statement table chunk is hard to retrieve with a plain-language question. Keyword ranks boilerplate (financial-statement index, exhibit lists) above it because the query is all common words. Candidate fix: contextual chunk prefix (P1).
- Lesson for the gold set: before calling a question a retrieval failure, list every chunk that answers it and accept all of them. The re-run after these fixes is the baseline above: `acn-buybacks` now ranks 2 hybrid and `acn-cash-fy25-prose` ranks 1.

### Earlier 15-question baseline (2026-10-17)

Hybrid, by tag (n is tiny: read direction, not decimals):

| Tag | n | hit@1 | hit@5 | hit@8 | MRR |
|---|---|---|---|---|---|
| numeric_table | 4 | 0.75 | 1.00 | 1.00 | 0.83 |
| narrative | 5 | 0.40 | 0.80 | 1.00 | 0.58 |
| multi_part | 2 | 0.00 | 0.50 | 1.00 | 0.16 |
| vocab_mismatch | 2 | 0.50 | 0.50 | 0.50 | 0.53 |
| 8k_by_date | 2 | 0.50 | 0.50 | 0.50 | 0.56 |

What it shows:

- Hybrid beats either path alone on hit@8 (0.87 vs 0.73 / 0.73), so fusion earns its keep overall.
- Fusion hurt one case: `avgo-contingent-liabilities` ranks 13 by vector, absent by keyword, 19 fused. The vocabulary-mismatch fix (P1) targets this.
- `acn-notes-offering-after-period-end` ranks 9 hybrid, just outside k=8, reproducing the known 8-K date failure. The "in July 2026" wording ranks 1. Supports the filing-date-hint item (P2).
- Auditor questions rank 4 and 6 hybrid; the answer is one short sentence inside a long audit-report chunk. Worth watching.
- Both multi-part questions only reach the answer by rank 5-8 without decomposition. This run does not use the decomposer, so it is a floor.
- Numeric tables are already strong (hit@5 = 1.00), so the table-header item (P1) is about the wrong-fiscal-year column, which this answer-text metric cannot see. It needs a column-aware gold entry before that item can be measured.
