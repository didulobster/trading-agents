# Retrieval improvement checklist

Ranked by priority: expected accuracy gain, divided by cost and risk, with
measurement first because nothing below can be judged without it.

Why each change was made, kept or dropped: `retrieval-decision-log.md`.

Status as of 2026-10-17: 49-question gold set, hybrid hit@8 0.94, hit@5 0.86,
MRR 0.63 (latest row of the done log).

Rule for every item: measure by answer content (does a top-k chunk contain the
answer string), never by chunk id, and rank the right chunk before changing
retrieval.

## P0. Build the measuring stick (do first)

- [x] **Answer-content gold set**, committed to git (~40-60 questions).
  Done: 49 questions in `app/edgar_research/scripts/retrieval_gold.yaml`.
  Each entry: question, ticker, filing, answer strings, shape tag.
  Seed from the ~100 real agent questions in the vault provenance files plus
  known failures (see "Known failures" below).
  Tags: numeric_table, numeric_prose, narrative, vocab_mismatch, multi_part, 8k_by_date.
- [x] **Runner** `app/edgar_research/scripts/eval_retrieval.py`: hit@k, MRR and
  first-hit rank per tag. Embeddings only, about $0.01 per run. Print a per-tag table.
- [x] **Record a baseline** in this file before any other change. See the done log.
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
  Tried and rejected 2026-10-17 (PR #176): no hit@8 gain, hit@1 fell.
- [x] **Company-name embedding** (shipped 2026-10-17, PR #177). Embed the SEC
  company name above each chunk. Hybrid hit@8 0.86 -> 0.95 on 37 questions.
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
| 2026-10-17 | Baseline refreshed: 37 questions (6 balance-sheet line items added) | 0.87 hybrid (31 q) | 0.86 hybrid (37 q) | hit@1 0.49, hit@5 0.76, MRR 0.60. The original 31 questions rank exactly as before, confirming the vector revert. New misses: acn-total-assets-fy25 (17), acn-cash-fy25 still missed. Reference for later changes |
| 2026-10-17 | Company-name embedding (PR #177) | 0.86 hybrid (37 q) | 0.95 hybrid (37 q) | 3 misses enter the top 8 (ranks 7-8); 10 up, 5 down by 1-2 ranks; hit@1 0.49 -> 0.46, MRR 0.60 flat |
| 2026-10-17 | ASML added, gold set at 48 questions (PR #179) | 0.95 hybrid (37 q) | 0.94 hybrid (48 q) | 10 of 11 ASML questions in the top 8; all three wrong-column tables found (ranks 1-2). hit@1 0.48, MRR 0.62. Reference for later changes |
| 2026-10-17 | Collapse repeated footnotes to the newest copy (D15) | 0.92 hybrid (49 q) | 0.94 hybrid (49 q) | hit@5 0.80 to 0.86, MRR 0.61 to 0.63; `acn-debt-use-of-proceeds` 9 to 1; six questions up, none down. Reference for later changes |

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

### ASML added: 48 questions (2026-10-17, PR #179)

ASML ingested (two 20-Fs, 1,190 chunks, each filing parsed as one whole-document section) and
11 questions added. First run, hybrid: 9 of the 11 ASML questions in the top 8, including all
three known wrong-column tables (FCF FY2023 rank 2, capex FY2025 rank 2, long-term debt rank 1).
All 37 ACN/AVGO questions ranked exactly as before.

| | hit@1 | hit@5 | hit@8 | MRR |
|---|---|---|---|---|
| hybrid, 48 questions (first run) | 0.46 | 0.79 | 0.92 | 0.60 |

- The two ASML misses were checked before being counted (rule from D5):
  - `asml-buyback-2025` (missed) was a gold defect. The entry accepted only the KPI tile, but
    the equity note ("total consideration of € 5,950.0 million") and the liquidity section also
    answer it. Fixed; keyword alone now finds an answer at rank 3 (was 20).
  - `asml-customer-concentration` (hybrid 16) is a real vocabulary miss. Two more answering
    chunks were added to the entry; keyword still finds none of them.
- Re-run after the fix (current reference):

  | 48 questions | hit@1 | hit@5 | hit@8 | MRR |
  |---|---|---|---|---|
  | vector | 0.38 | 0.83 | 0.92 | 0.55 |
  | keyword | 0.40 | 0.67 | 0.71 | 0.51 |
  | hybrid | 0.48 | 0.81 | 0.94 | 0.62 |

  Only the two corrected entries moved: `asml-buyback-2025` missed -> 1, and
  `asml-customer-concentration` stays at 16 hybrid (vector 6, keyword none: fusion with an
  empty keyword list pushes the vector hit down, as with `avgo-contingent-liabilities`).
  Misses left: `asml-customer-concentration` (16), `avgo-contingent-liabilities` (13),
  `acn-new-debt-vague` (14). All three are vocabulary or no-date questions.

### Company-name embedding trial (2026-10-17, PR #177)

Every ACN and AVGO chunk re-embedded with its SEC company name ("Accenture plc", "Broadcom
Inc.") above the content (about $0.014). Securities had been stored with the ticker as their
name; that is fixed too. Plain hybrid against the 37-question baseline:

| | hit@1 | hit@5 | hit@8 | MRR |
|---|---|---|---|---|
| hybrid before | 0.49 | 0.76 | 0.86 | 0.60 |
| hybrid with company name | 0.46 | 0.78 | 0.95 | 0.60 |

- hit@8 0.86 -> 0.95: three misses enter the top 8: `acn-cash-fy25` (missed -> 7),
  `acn-rpo-and-cash` (missed -> 8), `acn-total-assets-fy25` (17 -> 8). The only misses left are
  `avgo-contingent-liabilities` (13) and `acn-new-debt-vague` (14).
- 10 questions up, 5 down. The five down each lost 1-2 ranks and stayed in the top 8
  (`acn-revenue-fy26` 1 -> 2, `acn-icfr` 1 -> 2, `acn-9mo-opcash` 1 -> 2, `avgo-auditor` 4 -> 5,
  `acn-auditor` 6 -> 8). hit@1 falls by one question.
- Vector alone: hit@8 0.92 (0.77 on the 31-question set before).
- Cautions: the three gains land at ranks 7-8, on the edge of k=8; six of the 37 questions
  were added for this very problem; two tickers only. The ingestion path (`_embed` reading the
  stored name) is unit-untested; the trial used `reembed`.

### Balance-sheet chunk diagnosed (2026-10-17, one query embedding)

Question: `acn-cash-fy25`, plain-content vectors, filters ACN / 10-K / filed before 2026.

- The balance-sheet chunk (id 2585) ranks **111 of 359** by vector (cosine 0.574). The top hit
  scores 0.714. The cash-flow statement chunk that also holds the figure ranks 59; the MD&A
  sentence with the rounded figure ranks 7.
- The chunk's own vector is coherent: its nearest neighbours are the other ACN balance sheets
  (0.995 to the FY2024 one, 0.93 to the 10-Q ones). It embeds as "a balance sheet"; the
  question just does not land near that cluster.
- The likely reason is dilution. The chunk is 635 tokens in 1,698 characters (about 2.7
  characters per token against roughly 4 for prose), so most of its tokens are numbers.
  "Cash" appears twice, as one line item among about thirty. A question about one line item
  is far from a vector that averages thirty items and their figures.
- The top-ranked chunks are prose that repeats the question's words ("August 31, 2025",
  "consolidated", "cash"): the FX note, the equity statement, MD&A.
- Why the prefix failed fits this: a header line adds a few tokens to a vector dominated by
  hundreds of numeric ones.
- Tested (4 embeddings): each altered text scored against the question. The pool's rank-1
  similarity is 0.714 and rank 8 is 0.673.

  | Embedded text | Similarity | Would rank |
  |---|---|---|
  | original chunk (about 30 line items) | 0.574 | 111 |
  | same chunk, numbers stripped | 0.584 | 97 |
  | current-assets block (5 line items) | 0.626 | 55 |
  | title, column headers and the cash row alone | 0.748 | 1 |

- So it is not the numbers: removing them barely moves the score. It is the number of line
  items. Even five rows dilute the vector far below the top 8; one row with its title and
  column headers ranks first.
- Caveat: one question and one table, and the isolated row shares the question's wording
  ("Consolidated Balance Sheets", both dates), which flatters it. Real agent questions are
  phrased this way, but the result needs more table questions before it justifies a build.
- Repeated on seven balance-sheet questions (6 new gold entries, 14 embeddings). Vector ranks:

  | Question | Table chunk | Answer anywhere | Row alone |
  |---|---|---|---|
  | acn-cash-fy25 | 111 / 359 | 59 | 1 |
  | acn-total-assets-fy25 | 152 / 359 | 28 | 16 |
  | acn-goodwill-fy25 | 119 / 359 | 1 | 1 |
  | acn-long-term-debt-fy25 | 77 / 359 | 1 | 4 |
  | avgo-cash-fy25 | 2 / 168 | 1 | 1 |
  | avgo-total-assets-fy25 | 1 / 168 | 1 | 1 |
  | avgo-long-term-debt-fy25 | 1 / 168 | 1 | 1 |

- The dilution is specific to ACN's balance-sheet chunk (about 45 rows, assets and liabilities
  together). AVGO's balance sheet (about 18 rows, plus audit-report text) already ranks 1-2.
- For ACN goodwill and long-term debt, notes carry the same figures and rank 1, so the table
  miss costs nothing there. Only cash (59) and total assets (28) are real misses, and an
  isolated row fixes cash (1) but leaves total assets at 16.
- Unresolved confound: the AVGO chunk contains the company name ("BROADCOM INC."); the ACN chunk
  never says "Accenture". The failed prefix used the ticker "ACN", not the name.
- Decision: a row index is not justified yet. It would fix one of two real misses on this
  set. Test the company-name confound first (two embeddings).
- Company-name test (4 embeddings). Only the ACN balance-sheet chunk was re-embedded; every
  other chunk kept its plain vector:

  | Embedded text | acn-cash-fy25 | acn-total-assets-fy25 |
  |---|---|---|
  | original chunk | 111 | 152 |
  | ticker header, as in the failed prefix ("ACN 10-K filed ...") | 86 | 86 |
  | "Accenture plc Consolidated Balance Sheets" header | 5 | 1 |

- The company name, not the ticker, is what moves it. Two cautions before building on this:
  the header also repeats "Consolidated Balance Sheets", so name and title are not yet
  separated; and only one chunk changed, so this is an upper bound. Naming the company on
  every chunk also lifts every competitor, which is how the corpus-wide ticker prefix lost
  its gain.
- Name-only test (3 embeddings): "Accenture plc" alone above the chunk ranks it 8 for cash
  (sim 0.679) and 1 for total assets (0.745), against 5 and 1 with the title added. The
  company name carries almost all of the lift; the repeated title adds a little for cash.
  Still one chunk re-embedded against an unchanged pool, so still an upper bound.
- Direction this points to: index statement-table rows individually (title + column headers
  + one row) as extra retrieval entries that return the full table chunk. Carrying the column
  headers on every row would also address the wrong-fiscal-year column problem.

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
