# MSFT — Research Memo

**Date:** 2026-08-28
**Filings reviewed:**
- 10-K, filed 2026-07-29, period ended 2026-06-30 (FY2026)
- 10-K, filed 2025-07-30, period ended 2025-06-30 (FY2025)
- 10-K, filed 2024-07-30, period ended 2024-06-30 (FY2024)
- 10-Q (Q3 FY2026), filed 2026-04-29, period ended 2026-03-31 (used for Item 1A risk-factor content)
- 10-Q (Q2 FY2026), filed 2026-01-28, period ended 2025-12-31; 10-Q (Q1 FY2026), filed 2025-10-29, period ended 2025-09-30 (in corpus but not queried — their periods are superseded by the FY2026 10-K, whose period-end 2026-06-30 is the latest baseline)
- 8-Ks filed 2026-06-05 and 2026-07-29 (in corpus; no Item 4.01/4.02 indicated in corpus metadata; not analyzed in depth)

**Scope:** Filings-only forensic review. Contains no market prices, valuation multiples, company guidance, or consensus estimates. Input to an investment decision, not a rating.

## Executive Summary
- **Assessment: IMPAIRED, 10 red flags** — Free cash flow turned negative in FY2026 (−$44,708M) while revenue grew 17.8%, and Item 9A discloses a material weakness in internal control over financial reporting.
- Operating cash flow fell in each of the two most recent years ($118,548M FY2024 → $96,400M FY2025 → $71,240M FY2026) while additions to PP&E rose from $44,477M to $115,948M, so FCF went $74,071M → $31,849M → −$44,708M. Revenue rose in all three years; the MD&A attributes revenue growth to Microsoft Cloud, not acquisitions, so the cash divergence is not an acquisition artifact [Likely — capex and OCF disclosed, attribution inferred from Item 1].
- Operating cash flow trailed net income in both covered years (FY2025 0.92x, FY2026 0.60x) and net accounts receivable grew 46.9% against 17.8% revenue growth — a 29.1pp gap. Both accrual tests fail. [Certain]
- Leverage rose in every covered year and is now 3.52x total debt to consolidated operating income ($396,200M / $112,474M), the company is in a net-debt position of $354,900M, and the FY2027 maturity of $128,500M exceeds one full year of consolidated operating income. [Certain]
- SBC reached 17.8% of revenue in FY2026 ($58,900M), up 5.4 percentage points year over year, and Intelligent Cloud operating margin fell 7.71pp to 34.2% while that segment's revenue grew 29.7%. [Certain]
- Item 9A discloses an unremediated material weakness in controls over revenue recognition for multi-element cloud arrangements, and an SEC subpoena on the same subject is disclosed as pending with no amount accrued and no estimate of loss. [Certain]

## 1. Free Cash Flow Trend
FCF is defined as net cash from operations minus additions to property and equipment (capitalized software development is not disclosed as a separate investing line in retrieved excerpts; it is included within PP&E additions). [Certain]

| $M | FY2024 | FY2025 | FY2026 |
|---|---|---|---|
| Net cash from operations | 118,548 | 96,400 | 71,240 |
| Additions to property & equipment | 44,477 | 64,551 | 115,948 |
| **FCF** | **74,071** | **31,849** | **−44,708** |
| Revenue | 245,122 | 281,724 | 331,839 |

FCF is negative in the most recent covered year (calculated: 71,240 − 115,948 = −44,708) and fell in both covered years while revenue rose (FY2026 revenue +17.8% per the FY2026 10-K MD&A; calculated: (331,839 − 281,724)/281,724). Two separate limbs of item 1 are tripped: negative FCF in the most recent covered year, and FCF falling year over year while revenue grew. FCF margin FY2026 was −13.5% (calculated: −44,708/331,839), against +30.2% in FY2024. Operating cash flow itself — not only FCF — declined 26.1% in FY2026 (calculated: (71,240 − 96,400)/96,400) on 17.8% revenue growth, so the divergence is not attributable to the capex line alone. **Red flag, tagged structural**: no retrieved MD&A statement indicates the build-out will moderate, end, or normalize, and no retrieved statement describes the operating-cash-flow decline as non-recurring.

## 2. Risk Factor Changes (YoY)
The FY2026 10-K Item 1A section was not retrievable from this corpus (persistent retrieval failures — see Data Gaps), so a full FY2026-vs-FY2025 risk-factor diff could not be performed. The most recent Item 1A content retrievable is the Q3 FY2026 10-Q (filed 2026-04-29), which carries detailed AI-risk language: flawed AI algorithms/training methodologies, biased or inaccurate datasets, harmful or offensive AI-generated content, agentic AI systems requiring human oversight, over-reliance on personalized AI, and legal/regulatory liability from AI. The FY2025 10-K Item 1A emphasizes intense competition, low barriers to entry, and rapidly evolving technologies. No added or escalated risk factor naming an active proceeding, investigation, or quantified exposure was retrieved — no flag, but this item is only partially evidenced.

## 3. MD&A Narrative Shifts
The FY2026 10-K MD&A reports revenue increased 18% year over year, "driven by growth in Microsoft Cloud," consistent with retrieved revenue levels ($281,724M → $331,839M) and with Intelligent Cloud revenue growing 29.7% (calculated: (137,791 − 106,265)/106,265). FY2026 growth is not attributed to acquisitions, versus prior years when Activision Blizzard contributed to reported growth. The capex/AI-infrastructure portion of the FY2026 MD&A (expected FY2027 spending trajectory) was not retrievable, so a full topic-level diff of what newly appeared or disappeared could not be completed — partial finding only.

## 4. Stock-Based Compensation
SBC expense and SBC as a % of revenue (retrieved via extract_metrics): FY2024 $10,734M / 4.4%; FY2025 $34,890M / 12.4%; FY2026 $58,900M / 17.8% (independently calculated 17.75% for FY2026: 58,900/331,839). The ratio exceeds the 15% threshold in the most recent covered year and rose 5.4 percentage points year over year (calculated: 17.75 − 12.38), tripping both limbs of item 4. No one-time IPO vesting exists (mature filer), so the whole figure is run-rate. **Red flag, tagged structural**: the FY2026 10-K discloses expanded equity grants tied to AI-engineering retention and does not state the program is time-limited.

## 5. Segment Profitability
Microsoft allocates corporate-level costs to segments (generally by relative gross margin or headcount), so segment operating income sums to consolidated. [Certain]

| Segment | FY2024 rev / op inc | Margin | FY2025 rev / op inc | Margin | FY2026 rev / op inc | Margin |
|---|---|---|---|---|---|---|
| Productivity & Business Processes | 106,820 / 59,661 | 55.9% | 120,810 / 69,773 | 57.8% | 139,996 / 58,798 | 42.0% |
| Intelligent Cloud | 87,464 / 37,813 | 43.2% | 106,265 / 44,589 | 42.0% | 137,791 / 47,190 | 34.2% |
| More Personal Computing | 50,838 / 11,959 | 23.5% | 54,649 / 14,166 | 25.9% | 54,052 / 6,486 | 12.0% |

Consolidated operating income therefore fell to $112,474M in FY2026 from $128,528M in FY2025 (calculated: 58,798 + 47,190 + 6,486) — a 12.5% decline on 17.8% revenue growth. Every reported segment's margin fell in FY2026 while its revenue grew, except More Personal Computing, whose revenue was roughly flat (−1.1%). Intelligent Cloud fell 7.71pp (calculated: 34.25% − 41.96%) on revenue growth of +29.7%, and Productivity & Business Processes fell 15.8pp on revenue growth of +15.9%. Both exceed the 200bp threshold with growing revenue. **Red flag, tagged structural**: the retrieved MD&A attributes the compression to AI infrastructure depreciation and does not state it will moderate.

## 6. Debt, Leverage & Maturity Wall
Total debt (current portion + non-current long-term debt, excluding operating lease liabilities): FY2024 $44,937M; FY2025 $168,400M; FY2026 $396,200M. Operating lease liabilities: FY2024 $19,077M; FY2025 $22,861M; FY2026 not retrieved. Cash + short-term investments: FY2024 $75.5B; FY2025 $62.1B; FY2026 $41.3B.

| | FY2024 | FY2025 | FY2026 |
|---|---|---|---|
| Total debt / operating income | 44,937/109,433 = 0.41x | 168,400/128,528 = 1.31x | 396,200/112,474 = 3.52x |
| Net debt (debt − cash+ST inv) | −$30,563M | +$106,300M | +$354,900M |

Leverage rose in every covered year and the FY2026 ratio of 3.52x exceeds the 3.0x threshold — **both limbs of 6(a) tripped**. The company moved from a net-cash position in FY2024 to net debt of $354,900M in FY2026. Maturity schedule (face value, FY2026 10-K debt footnote): FY2027 $128,500M; FY2028 $61,300M; FY2029 $44,800M; FY2030 $22,600M; FY2031 $18,400M; thereafter $120,600M; total $396,200M. The FY2027 maturity of $128,500M is 1.14x of FY2026 consolidated operating income (calculated: 128,500/112,474) and falls within 24 months of the 2026-06-30 period end — **6(b) tripped**. Weighted-average interest rate not retrieved. Amortization of acquired intangibles fell from $6.0B (FY2025) to $4.7B (FY2026), so the leverage deterioration is not a purchase-accounting artifact: adding it back gives FY2026 396,200/(112,474 + 4,700) = 3.38x, still above the threshold [Certain — amounts disclosed; conclusion is arithmetic].

## 7. Contingent Liabilities
The FY2026 10-K Commitments & Contingencies note discloses an SEC subpoena, received 2026-02-11, seeking documents concerning revenue recognition and the timing of revenue on multi-element commercial cloud arrangements for FY2024 through FY2026. The filer states it is cooperating, that the matter is at an early stage, that **no amount has been accrued** because a loss is not reasonably estimable, and that an adverse outcome could be material. [Certain] Item 3 Legal Proceedings additionally references a related consolidated putative securities class action filed 2026-03-30 in the Western District of Washington, also unaccrued. [Certain] **Red flag under item 7 on both limbs**: a loss contingency disclosed as unaccrued, and a regulatory/enforcement matter disclosed as pending. Tagged **structural** — no retrieved statement describes either matter as expected to resolve or as non-recurring.

## 8. Customer & Revenue Concentration
**Data Gap.** No customer-concentration disclosure (customers accounting for 10% or more of revenue or accounts receivable) or geographic/product concentration note was retrievable. Presence or absence of a 10% customer could not be confirmed.

## 9. Share Count & Capital Return
**Data Gap.** Diluted weighted-average shares outstanding, cash used for share repurchases, cash used for acquisitions, and goodwill balances were not retrievable despite multiple queries. The dilution-vs-repurchase question and the capex/M&A/repurchase cash-deployment split cannot be answered from this corpus; no inference is substituted. Goodwill as a % of total assets is likewise unknown, so the serial-acquisition check cannot be run — note that FY2026 MD&A attributes growth to cloud, not acquisitions, and acquired-intangible amortization is rolling off, suggesting no large acquisition closed in the covered years [Likely].

## 10. Internal Controls & Governance
(a) Item 9A states that management concluded internal control over financial reporting was **not effective** as of 2026-06-30 owing to a material weakness in the design and operating effectiveness of controls over the identification and allocation of performance obligations in multi-element commercial cloud arrangements. Remediation is described as in progress and not complete as of the filing date, and the independent registered public accounting firm issued an adverse opinion on ICFR. [Certain] **Red flag under item 10(a).** (b) The independent registered public accounting firm (Deloitte & Touche LLP, since 1983) is unchanged across the covered filings, and no 8-K Item 4.01/4.02 was indicated in corpus metadata. No flag on 10(b). (c) No material related-party transaction was retrievable; see Data Gaps.

A disclosed material weakness undermines the reliability of every retrieved figure in this memo, and the affected control is the one governing revenue recognition — the line item that drives the revenue-growth figures cited throughout. This is stated here rather than left implicit because the tier assignment below turns on it.

## 11. Earnings Quality
(a) Net income vs OCF: FY2025 NI $105,000M vs OCF $96,400M (ratio 0.92x); FY2026 NI $118,600M vs OCF $71,240M (ratio 0.60x, calculated). **Operating cash flow trailed net income in both covered years — item 11(a) tripped**, and the gap widened rather than closed. [Certain] (b) Receivables vs revenue: net accounts receivable were $68,400M (2025-06-30) and $100,500M (2026-06-30), growth of 46.9% (calculated: (100,500 − 68,400)/68,400) against revenue growth of 17.8%. The 29.1pp gap exceeds the 20pp threshold — **item 11(b) tripped**. [Certain] Days sales outstanding rose from 88.6 to 110.5 on the same figures. The two accrual tests fail together and in the same direction, which is the pattern the rubric's persistent-accrual-gap trigger describes.

## 12. Backlog / RPO
Remaining performance obligations were $368,000M at 2025-06-30 and $301,400M at 2026-06-30, a decline of 18.1% (calculated: (301,400 − 368,000)/368,000) against revenue growth of +17.8%. **Item 12 tripped on its first limb** (RPO declined year over year); the second limb is tripped as well, the gap being 35.9 percentage points against a 20pp threshold. The retrieved MD&A attributes the decline to shorter average contract duration in commercial bookings and does not state the shift is temporary, so tagged **structural**. [Certain]

## Data Gaps
- **Item 8, Item 9 (entire items):** fully gapped — the requested disclosures exist in the FY2026 10-K but were not retrievable from this corpus despite repeated queries; counted as 2 of 12 top-level items fully gapped.
- **Item 2:** FY2026 10-K Item 1A text not retrievable; only Q3 FY2026 10-Q Item 1A and FY2025 10-K Item 1A fragments were obtained.
- **Item 3:** FY2026 MD&A capex/spending trajectory commentary not retrievable; topic-level diff incomplete.
- **Item 6:** FY2026 operating lease liabilities and debt interest rates not retrievable.
- **Item 10(c):** related-party-transaction note not retrievable.
- Q1/Q2 FY2026 10-Qs were not queried because their period-ends (2025-09-30, 2025-12-31) are superseded by the FY2026 10-K's 2026-06-30 baseline.
- Standing scope exclusions: no market prices, valuation multiples, company guidance, or consensus estimates were used or are available in this corpus.

## Red-flag rubric
A finding is a red flag if and only if it trips the threshold below for its item. These are the thresholds referenced in the Assessment section — do not invent, substitute, or soften one, and do not raise a flag on an item whose threshold is not met, however concerning the finding reads.

1.  Free cash flow is negative in the most recent covered year, OR free cash
    flow fell year over year while revenue grew.
2.  A risk factor was added or escalated that names an active proceeding,
    investigation, or quantified exposure. Boilerplate rewording is not a flag.
3.  Management's explanation of a result contradicts a figure retrieved in
    this review, OR a driver discussed in the prior period disappears with no
    explanation.
4.  Run-rate SBC exceeds 15% of revenue in the most recent covered year, OR
    rose more than 3 percentage points year over year. One-time IPO vesting
    is excluded from run-rate for this test and reported separately.
5.  A reported segment's operating margin fell more than 200 basis points
    year over year while that segment's revenue grew.
6.  (a) Total debt / consolidated operating income exceeds 3.0x, OR rose in
        every covered year.
    (b) Any single maturity within 24 months of the latest period-end
        exceeds one year of consolidated operating income.
7.  Any loss contingency disclosed as unaccrued, OR any regulatory,
    sanctions, or enforcement matter disclosed as pending or under review.
8.  Any single customer is 10% or more of revenue or of accounts receivable,
    OR the filer's own concentration note flags a geographic or product
    concentration.
9.  Diluted weighted-average shares outstanding rose year over year despite
    repurchases, OR M&A was the largest use of cash across the covered period
    while goodwill exceeds 30% of total assets.
10. (a) Item 9A discloses a material weakness in ICFR.
    (b) The independent registered public accounting firm changed across the
        covered filings, or an 8-K Item 4.01/4.02 was noted.
    (c) A related party transaction is material and involves an officer,
        director, or controlling holder.
11. (a) Operating cash flow trailed net income in both covered years.
    (b) Accounts receivable growth exceeded revenue growth by more than 20
        percentage points.
12. RPO or backlog declined year over year, OR grew more than 20 percentage
    points slower than revenue. "Not disclosed by this filer" is never a flag.

A disclosed explanation NEVER cancels a flag. The threshold decides whether a
flag exists; the explanation decides only how it is tagged. A capex-driven
fall in free cash flow is still a flag under item 1 — tagged, not omitted.
Judging a tripped threshold to be benign, expected for the sector, or already
understood by the market is not a reason to drop it, and "the company
explained it" is not either.

Tagging, which is also decided by a test and not by impression:
- cyclical/temporary — ONLY when the filer itself states that the driver is
  non-recurring, or expects it to moderate, end, or normalize. Quote or cite
  that statement when you use this tag.
- structural — everything else, including a driver described as ongoing, a
  multi-year program with no stated end, and a threshold tripped with no
  disclosed driver at all.
Silence defaults to structural. "This looks like a normal investment cycle"
is an impression, not a disclosure; a build-out the filer never says will
moderate is structural however ordinary it seems.

## Assessment
Evidentiary coverage gate: 2 of 12 top-level items are fully gapped (items 8, 9), within the allowed four, and item 10(a) — the ICFR/material-weakness question — is answered (material weakness disclosed). A tier is therefore assignable.

**Verdict: IMPAIRED**

Red flags:
- Item 1: FCF negative in FY2026 (−$44,708M) and falling in both covered years while revenue grew. **Structural.**
- Item 4: SBC 17.8% of revenue, above the 15% threshold, and +5.4pp year over year. **Structural.**
- Item 5: Intelligent Cloud margin −7.71pp and Productivity & Business Processes −15.8pp, both on growing revenue, both above the 200bp threshold. **Structural.**
- Item 6(a): total debt/operating income 3.52x, above 3.0x, and risen in every covered year. **Structural.**
- Item 6(b): FY2027 maturity of $128,500M is 1.14x one year of consolidated operating income, inside the 24-month window. **Structural.**
- Item 7: SEC subpoena on revenue recognition disclosed as pending and unaccrued; related securities class action also unaccrued. **Structural.**
- Item 10(a): material weakness in ICFR over revenue recognition, unremediated, with an adverse ICFR opinion. **Structural.**
- Item 11(a): OCF trailed net income in both covered years (0.92x, then 0.60x). **Structural.**
- Item 11(b): receivables grew 46.9% against 17.8% revenue growth, a 29.1pp gap. **Structural.**
- Item 12: RPO fell 18.1% year over year while revenue grew 17.8%. **Structural.**

Earnings quality tier: **IMPAIRED** — the tier is forced independently by two of the rubric's IMPAIRED triggers, either of which alone would be sufficient: a disclosed material weakness in ICFR (item 10(a)), and a persistent accrual gap in which operating cash flow trailed net income in every covered year and receivables outgrew revenue by 29.1 percentage points.

Single finding a portfolio manager most needs to investigate: **whether reported revenue is collectible and correctly recognized at all — receivables grew 46.9% against 17.8% revenue growth, operating cash flow fell 26.1% while reported net income rose, the SEC has subpoenaed the revenue-recognition process, and the control governing that process is disclosed as materially weak. Every one of those four points to the same account, and until the material weakness is remediated no retrieved figure in this memo carries its normal weight.**
## Unverified Figures and Quotations

The following appear in this memo but were not returned by any tool during this run. Verify against the filing before relying on them.

- **figure:** `4.02`
  - context: …6-05 and 2026-07-29 (in corpus; no Item 4.01/4.02 indicated in corpus metadata; not analyzed i…

- **quote:** `Not disclosed by this filer`
  - context: …points slower than revenue. "Not disclosed by this filer" is never a flag.  A disclosed…
- **quote:** `the company
explained it`
  - context: …not a reason to drop it, and "the company explained it" is not either.  Tagging, whic…
- **quote:** `This looks like a normal investment cycle`
  - context: …lence defaults to structural. "This looks like a normal investment cycle" is an impression, not a discl…
## Unbacked Derivations

The following figures match a `calculate()` call that was rejected during this run and never successfully retried. The number itself may be correct, but no passing tool call in this run's trace validates how it was derived — re-derive it with a passing calculate call before relying on it.

## Underived Arithmetic

The following figures were not returned by any tool, but each equals a sum or difference of other figures in this memo that were independently verified — a total stated in prose instead of run through calculate(). The inputs are real; only this arithmetic step is unvalidated. Lower risk than the figures above — re-derive with calculate() to confirm.

