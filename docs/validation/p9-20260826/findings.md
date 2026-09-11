# Phase 9 battery — findings (partial: 3 of 6)

Battery `p9-20260826`, `as_of=2026-08-26`, `--max-usd 1.10`, git `9e308cb`.
Halted at 3/6 by Anthropic credit exhaustion. True spend **$2.9874**.

## Criteria

| # | criterion | result |
|---|---|---|
| 1 | corpus coverage | **PASS** (6/6 after NFLX ingest) |
| 2 | 6/6 runs complete | **FAIL** — 3/6 (credit exhaustion, not a pipeline defect) |
| 3 | schema-valid | 3/3 of the memos that exist validate |
| 4 | verifier clean (in-band) | 0 `decision_failed` artifacts — but see §"what the verifier missed" |
| 5 | zero Class A/B/E | **PASS** (an earlier FAIL was withdrawn — see the correction below) |
| 6 | **C/D within ceiling** | **FAIL — 5 across 3 memos** (ceiling: ≤1/memo, ≤3/battery) |
| 7 | single as_of_date | **PASS** — all three carry 2026-08-26 |
| 8 | verdict stability | not run |
| 9 | cost ≤ $4.00 | **PASS at 3 runs** ($2.99); would have exceeded at 6 |

Audit order was **ACN → NFLX → AVGO**, deliberately not run order (§6.3).
**Bias disclosure:** the verdicts were visible to me before the audit began,
because each run's result was reported as it landed. §6.3 says not to read
the recommendation first. That was not possible here and is recorded rather
than papered over.

## CORRECTED: no Class A. The auditor's method was the defect.

This document previously reported a Class A fabricated figure on AVGO
("$70–100B AI financing debt"). **That was wrong.** The figure is correctly
sourced — the AVGO news digest carries six items saying so:

- "Broadcom debt deal expected to reach upwards of **$70 billion**, sources say"
- "Broadcom in talks to raise **$70-80 billion in debt** for chip financing deal"
- "Broadcom seeks up to **$80 billion in debt** for AI chip deal"
- "Broadcom seeks up to **$100 billion in debt financing** for AI chip deals"
- "Broadcom Eyes Up to **$100 Billion AI Financing Deal**"
- "Broadcom pursuing up to **$100 billion debt deal** to fund Anthropic"

The companion claim that the memo "contradicts its own source" on
off-balance-sheet financing was also wrong: the digest carries both
framings, and the memo chose the better-supported one.

**Cause.** Absence was established with `grep -oE ".{50}\b70\b.{50}"`,
which needs fifty characters of trailing context on the same line. The
headline line ended sooner, grep printed nothing, and nothing was read as
absent. The same trailing-context bug was in the `$100 billion` and
`off-balance-sheet` searches, so all three legs failed together and none
contradicted the others.

**Lesson, stated as a rule for the next audit:** an absence claim needs a
positive control. "grep found nothing" is evidence about the grep until a
search known to match has been run against the same file. Notably the
new tiered verifier, run over this same memo, reported `78%` and `5.4` as
debate-originated and did *not* report `70` or `100` — the tool was right
where the auditor was not.

**Criterion 5 (zero Class A/B/E) PASSES** on the three memos audited.

## What the battery did measure: the guard's precision is inverted

Every "may be fabricated" figure reported across the three memos was
correct, and every one was a millions-to-billions restatement exact
containment structurally cannot see:

| flagged | actually | memo |
|---|---|---|
| 63.9 | $63,887M revenue | AVGO |
| 35.8 | $35,819M FY2023 revenue | AVGO |
| 2.2 | 6.1% × $35,819M SBC | AVGO |
| 5.7 | $5,747M FY2024 SBC | AVGO |
| 78% | 63,887/35,819 − 1 | AVGO |
| 10.1 | $10,149M operating cash flow | NFLX |
| 69.7 | $69,673M revenue | ACN |

**Seven false positives, zero true positives.** A guard whose warnings are
reliably wrong is worse than no guard — it trains the reader to skip the
category. This is the defect the battery actually established, and it is
fixed.

Decision 2's structural argument about containment stands on its own
(Phase 5's `21.9%` is its evidence), but **this battery contributed no live
instance of it** — the one candidate was the auditor's error.

## Class C / D — counted against the ceiling

**NFLX — Class D, wrong unit (material).**
`reasoning`: "leverage fell **41 basis points** gross and **34 basis points**
net". The corpus says "a **0.41-turn** improvement" (1.50x → 1.09x) and "a
**0.34-turn** improvement" (0.75x → 0.41x). Turns are not basis points. As
written, a reader sees a 0.41% change; the real move is a 27% reduction in
gross leverage — two orders of magnitude understated, on the memo's lead
positive claim. The *same memo* states it correctly in
`risk_debate_summary`: "1.09x gross and 0.41x net". Internally inconsistent.

**ACN — Class C, directional/state mischaracterization.**
`watch_items`: "Stock price closes below 200-day moving average (201.73) for
five consecutive trading days, confirming intermediate downtrend entry
[RFF6D6]." Last close is **181.38** — already far below the 200-day. The
memo's own `technical_signal` says "notably below the 200-day average at
201.73". A watch item whose trigger is already satisfied is not an
observable; it reads as a future risk that is a present state.

**ACN — Class D, dropped qualifier.**
`bull_case` / `risk_debate_summary`: "net cash of $6.3B and leverage of
0.50x". The corpus labels 0.50x explicitly as **gross** leverage. The
sentence uses "net" for the cash figure and drops the qualifier on the
ratio. FY2025 net leverage is negative (net cash), so an unqualified
"leverage of 0.50x" beside "net cash" invites the wrong read. This is the
gross/net conflation family of known gap #1.

**AVGO — Class D, period label.**
`reasoning`: "FY2025 FCF of $17.2B on $63.9B revenue represents negative
operating leverage—**a 78% revenue increase** yielded flat cash generation."
The 78% is FY2023→FY2025 *cumulative*. FY2025 revenue growth was **23.9%**.
The arithmetic is right and both endpoints trace; the period it belongs to
is never stated, inside a sentence otherwise about FY2025.

**AVGO — Class D, unit notation.**
"$2.80x", "$2.61x" — currency signs on leverage multiples. Minor, but it is
the same carelessness about what a number *is* that produced the NFLX
basis-points error.

### Tally

| memo | A | B | C | D | C+D |
|---|---|---|---|---|---|
| ACN | 0 | 0 | 1 | 1 | **2** |
| NFLX | 0 | 0 | 0 | 1 | **1** |
| AVGO | 0 | 0 | 0 | 2 | **2** |
| **total** | **0** | 0 | 1 | 4 | **5** |

Ceiling is ≤1 per memo and ≤3 per battery. **ACN and AVGO breach the
per-memo ceiling; the battery breaches at 5 over three memos** — and the
battery was meant to be six.

## Not counted, recorded

- **ACN, spliced quote.** The memo quotes the 10-K as "…forfeiture of
  profits, suspension or debarment." The source reads "…forfeiture of
  profits, **suspension of payments, fines, and** suspension or debarment
  **from federal government contracting**." Silent elision, no ellipsis —
  which `RiskFactor.evidence_quote`'s own schema forbids ("never spliced or
  elided with '...'"). Not counted because stretching Class D from number
  labels to quotation mechanics would be inventing a class mid-audit, which
  §6.3 exists to prevent. Logged as a schema-compliance defect instead.
- **Unverified quote spans are dense and rising with memo complexity:** ACN
  4 claims, NFLX 6, **AVGO 24**. The pipeline flags these itself. AVGO's 24
  is not a rounding issue — it is most of the debate's citations.
- **AVGO verdict rests on 2 samples, not 3.** One trial was dropped by the
  citation/fabrication guard, so `unresolved` is partly an artifact of a
  lost sample: two disagreeing samples *cannot* produce a majority. This is
  the third independent observation of AVGO verdict instability (Phase 6,
  Phase 8, now).

## §8 triage — the ceiling rule governs

1. ~~Class A defect present~~ — **withdrawn**, see the correction above.
2. **C/D ceiling exceeded** → "Stop the phase. Do not fix and rerun; the
   finding is that the gap's rate is higher than Phase 7 evidence
   supported, and the right next move is characterizing the gap, not
   patching six memos."

Rule 2 stands on its own, and it says stop. Phase 7 saw **one** confirmed C-class
instance across five memos. This battery saw **five** C/D across three, plus
a Class A. That is not the same system behaving slightly worse; it is
evidence the Phase 7 rate was an underestimate.

The most likely reason, stated as the inference it is: Phase 7's battery
averaged **$0.448/run**, which is not consistent with runs that paid for
real fundamentals (~$0.85/run measured here). Its `cost_log` lines predate
the `run_id` field, so this cannot be confirmed per-run — but only **one**
`trading-fundamentals` call is on record for 2026-08-26 at all, against a
five-ticker battery, and one of those five (NFLX) is independently known to
have run `--only technical`. So Phase 7 very likely audited memos with far
less live numeric content than these three, which would depress its
observed defect rate for reasons that have nothing to do with the pipeline
getting worse since.
