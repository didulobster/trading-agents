# Discrimination probe — pre-registration (2026-08-29, written before any run)

Written before spending anything, so the reading of the result is fixed in
advance and cannot be chosen after seeing it.

## The question

The deepseek Phase 9 battery returned `hold` on 6/6 watchlist tickers, every
one unanimous 3/3, confidence 0.92–0.97 and flat. Two readings fit:

- **A — low noise:** deepseek is genuinely steadier than Haiku on debates
  Haiku finds ambiguous, and `hold` is the right answer for all six.
- **B — no discriminating power:** the pipeline returns `hold` at high
  confidence whatever the evidence says.

Criterion 8 (verdict stability under re-run) cannot separate these: a system
with no discriminating power is perfectly stable. Only changing the input can.

## Design

One channel is manipulated — the fundamentals report text — with everything
else held at the battery's settings: same `as_of` (2026-08-28), same models
(deepseek-v4-flash for every role), same prompts, same majority-of-3 sampling,
live technical and news exactly as the battery had them.

The manipulation is legitimate rather than adversarial. `_grounded_corpus` is
built from the analyst reports in state, so a substituted fundamentals summary
is grounded by construction: quotes resolve, the number guards check against
it, `verify_decision_memo` passes. Nothing is being smuggled past a guard;
the pipeline sees a normal, internally consistent report that happens to say
the company is in trouble.

Distress is defined by **the report's own red-flag rubric**, which is copied
through untouched. The distressed variants trip:

| ticker | baseline | variant | red flags | IMPAIRED triggers |
|---|---|---|---|---|
| MSFT | MIXED, 1 flag | IMPAIRED, 10 flags | 1, 4, 5, 6a, 6b, 7, 10a, 11a, 11b, 12 | material weakness; persistent accrual gap |
| ACN | MIXED, 2 flags | IMPAIRED, 8 flags | 1, 5, 6a, 7, 10a, 11a, 11b, 12 | material weakness; persistent accrual gap |

Headline injected facts: negative or falling free cash flow, operating cash
flow trailing net income in both covered years, receivables outgrowing revenue
by 29–38pp, an unremediated material weakness in ICFR over revenue
recognition with an adverse auditor opinion, and an unaccrued SEC/DOJ
enforcement matter on the same account.

## Predictions, fixed in advance

- **P1 (verdict):** if the pipeline discriminates, at least one of the two
  distressed runs returns `sell`. A `hold` on a memo whose own fundamentals
  section reads IMPAIRED with a material weakness is not a defensible verdict
  at any confidence.
- **P2 (confidence):** if the pipeline discriminates, confidence falls at
  least 0.15 below the ticker's battery baseline (MSFT 0.94, ACN 0.94).
- **P3 (perception):** the memo's bear case cites at least three of the
  injected facts. This separates *not seeing* the evidence from *seeing it and
  not acting on it*.

## How each outcome is read

| verdict | P3 (bear case cites the distress) | reading |
|---|---|---|
| `sell` | yes | Reading A. The system discriminates; six holds were about the companies. |
| `hold` | yes | Reading B, localized to verdict assignment: perception works, the verdict is not a function of what was perceived. |
| `hold` | no | Reading B, upstream: the evidence never reaches the verdict at all. |
| `buy` | either | Something is wrong beyond discrimination; investigate before drawing any conclusion. |

A `hold` at confidence ≥0.90 on both tickers is the single most informative
outcome and would outrank the eight Phase 9 criteria that pass, because those
criteria cannot distinguish a system that is right from one that says the same
thing regardless.

## Scope of what this can show

- **Two tickers, one arm, one manipulated channel.** Technical and news stay
  real, so the distressed input is internally conflicted by construction: a
  company whose filings read IMPAIRED while its tape and press do not. That
  conflict is a reason a *human* might hold. It is not a reason to hold at
  0.94 confidence without the memo saying so, which is what P3 tests.
- **The variants are more credible than the baseline, not less.** Injected
  figures carry no "unverified figure" appendix entries, so if anything the
  distressed evidence looks better sourced than the real report's.
- **A null result here is weaker than a positive one.** If the verdict moves,
  the system discriminates. If it does not move, the honest conclusion is
  "it did not move on this manipulation", and the next question is whether
  any manipulation moves it — which the exceptional arm would answer.
