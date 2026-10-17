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
- [ ] **Split compound questions before retrieval, not only on regex signals.**
  A 3-part question ranked the ICFR chunk nowhere; asked alone it ranked 1.
  The regex gate in `query_decomposer` misses compound questions with no
  trigger word.
- [ ] **Filing-date hints for 8-K questions.** "after <period-end>" ranked the
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

### Baseline detail (2026-10-17, `eval_retrieval --depth 20`)

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
