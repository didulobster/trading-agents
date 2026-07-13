# Dogfooding Log — Phase 3 (Real Usage)

Goal: does this tool change how I think about a position, not just "did retrieval work."

---
## [Date] — [Ticker] — [one-line topic]

**Question asked:** 
**Filters used:** 
**Answer:** [paste or summarize]
**Citations checked?** Y/N — [what you found when you spot-checked one]

**Did this change my thinking?** 
**Would I have found this faster by reading the 10-K myself?** 
**Question I wanted to ask but didn't:** 

**Tag:** [useful / neutral / misleading / didn't trust it / self-censored]


## [2026-07-10] — [FIG] 

**Question asked:** 
Does cost-of-revenue growth rate decelerate relative to revenue growth for the past 4 years for Figma

**Filters used:** NA

**Answer:** The provided context does not contain sufficient information to answer this question. The excerpts describe what cost of revenue consists of and general expectations for its behavior [FIG 10-K 2026 §Item 7], but they do not provide the specific cost of revenue figures or revenue figures for the past four years needed to compare growth rates. Only sales and marketing, general and administrative, and other income figures for 2025 vs. 2024 are shown in the provided excerpts—not cost of revenue or multi-year revenue data.

**Citations checked?** [FIG 10-K 2026 §Item 7] does describe cost-of-revenue composition and general behavior, consistent with the answer's characterization. Did not contain multi-year figures, also consistent.

**Did this change my thinking?** No but confirmed FIG has a very short public reporting history, which is itself a real data point for evaluating the stock (limited track record).

**Would I have found this faster by reading the 10-K myself?** N/A — question wasn't answerable from any source, not a speed comparison.

**Question I wanted to ask but didn't:** How has FIG's cost-of-revenue evolved relative to revenue since its IPO? 

**Tag:** LLM honesty win — system correctly declined rather than fabricating a 4-year trend that doesn't exist. Process lesson: check corpus-status / filer history before asking multi-year questions on recently-IPO'd companies.



## [2026-07-10] — [FIG] 

**Question asked:** 
what is the moat of FIG

**Filters used:** FIG

**Answer:** Figma's competitive moat, based on the filing, includes the following elements:
**Broad, integrated platform**
Figma positions itself as a "connected platform" spanning the full product development workflow — from ideation (FigJam), presentations (Figma Slides), design (Figma Design, Figma Draw), development handoff (Dev Mode), website publishing (Figma Sites), marketing assets (Figma Buzz), and AI-driven prototyping (Figma Make) [FIG 10-K 2026 §Item 1, FIG 10-K 2026 §Item 7]. In 2025 it "doubled [its] product portfolio" with four new products [FIG 10-K 2026 §Item 7].

**AI integration**
Figma has "embedded AI deeply across the Figma platform," including Figma Make (text prompts → working prototypes or web apps) and AI editing on the Figma canvas. It has also built an MCP server that connects code-editor agents directly to Figma designs [FIG 10-K 2026 §Item 1, FIG 10-K 2026 §Item 7].

**Community and brand**
Figma highlights deep community ties: "Friends of Figma" chapters worldwide, its annual Config conference (started 2020), livestreams, forums, and social channels that create "active dialogue" and a peer network [FIG 10-K 2026 §Item 1]. An "engaged global community of users" is cited as a principal competitive factor [FIG 10-K 2026 §Item 1].

**Intellectual property**
As of December 31, 2025: 22 issued U.S. patents, 78 U.S. patent applications, 159 non-U.S. pending patent applications, and a trademark portfolio of 103 registered trademarks and 98 pending applications across 62 countries, Hong Kong, and the EU. U.S. patents expire between 2034 and 2055 [FIG 10-K 2026 §Item 1].

**Security and privacy posture**
Figma's security program has "achieved several internationally-recognized certifications and industry standard attestation reports," with dedicated privacy and security teams [FIG 10-K 2026 §Item 1].

**Talent and culture**
1,886 Figmates as of December 31, 2025, with five stated cultural values driving execution [FIG 10-K 2026 §Item 1].

**Competitive factors Figma cites as its basis for competing favorably**
Breadth of platform; ease of use; collaboration; features/quality; automation; integrations; customization, security, compliance, scalability, reliability; market vision; speed of innovation; customer base size and user adoption; pricing; sales/marketing; brand; engaged global community; and customer experience [FIG 10-K 2026 §Item 1].

Note: The filing does not use the word "moat" or explicitly rank these as durable competitive advantages — the above are the competitive strengths and differentiators Figma discloses. The filing also notes the industry is "highly competitive, and rapidly evolving," with competition from full-suite players, point tools, design-to-code/AI startups, and internal customer-built solutions [FIG]

**Moat quality (my analysis, not the filing):** Most of the disclosed list is table stakes, not moat.
- **Real moats:** (1) *Collaboration-driven switching costs* — multiplayer design systems, component libraries, and cross-functional workflows create genuine org-level lock-in. Buried in the 10-K as one "competitive factor" of fifteen; it IS the moat. (2) *Brand / default-tool status* — became the verb; education → employer pipeline; community is a self-reinforcing intangible asset.
- **Table stakes (NOT moats):** security certs (every SaaS has them), software patents (rarely stop UX/SaaS competition), "culture" (not underwritable).
- **Mislabeled — analytically backwards:** AI integration is presented as a strength but is the *vector of attack* (Cursor, Claude Code, v0, Lovable) and the driver of Q1'26 gross-margin compression (91%→79%). Not a moat.
- One-liner: **Two real moats (collaboration lock-in + designer mindshare) wrapped in table stakes presented as if also moats.**


**Citations checked?** FIG 10-K 2026 §Item 1 confirmed for the strengths list. NOT independently re-pulled this session: patent/trademark counts (22/78/159, 103/98) and "doubled portfolio / 4 products" — trusting prior extraction. Headcount 1,886 cross-checks vs. external (~1.89K, Jul 2026). Moat-quality section is my judgment, not filing text.


**Did this change my thinking?** Yes

**Would I have found this faster by reading the 10-K myself?** No for extraction; but the 10-K alone would NOT have surfaced the moat-quality distinction — that needs analysis on top of retrieval.


**Question I wanted to ask but didn't:** Is Figma's collaboration moat durable if AI codegen routes around the design canvas entirely — i.e., is the switching-cost moat built on a workflow AI is making optional? Sub-question to make it answerable: what share of Figma's value is single-player (individual designing) vs. multiplayer (team collaborating)? Multiplayer = the defensible moat; single-player = exactly what AI tools pick off first. (Ties the moat question and the gross-margin/bear thesis into one — same phenomenon, two angles.)


**Tag:** Useful


## [2026-07-12] — ACN — Total revenue (sanity check)

**Question asked:** What was Accenture's total revenue for the most recent fiscal year?
**Filters used:** ACN 
**Answer:**
Accenture's total revenue for fiscal 2025 (most recent fiscal year, ended August 31, 2025) was $69,672,977 thousand [ACN 10-K 2025 §Item 16].

Citations checked? Y/N — Yes, exist in Part II > Item 6 > [Reserved]

Did this change my thinking?
Would I have found this faster by reading the 10-K myself? Yes
Question I wanted to ask but didn't:

Tag: useful 


[2026-07-12] — ACN — Financial Services segment revenue

Question asked: What was Accenture's revenue from the Financial Services industry group?
Filters used: ACN
Answer:
- Fiscal 2025: $12,773,856 thousand [ACN 10-K 2025 §Item 16]
- Fiscal 2024: $11,610,225 thousand [ACN 10-K 2024 §Item 16]
- Fiscal 2023: $12,131,531 thousand [ACN 10-K 2023 §Item 16]
- Fiscal 2022: $11,810,582 thousand [ACN 10-K 2023 §Item 16]
- Fiscal 2021: $9,932,523 thousand [ACN 10-K 2023 §Item 16]

Citations checked? Y/N — yes, exist in  Part IV > Item 16 > Form 10-K Summary

Did this change my thinking?
Would I have found this faster by reading the 10-K myself? yes
Question I wanted to ask but didn't:

Tag: useful 


## [2026-07-12] — ACN — AI risk factor tone vs MD&A framing

**Question asked:** Does the tone of Accenture's AI-disruption risk factor 
(Item 1A) match how GenAI is framed in the bookings/strategy narrative (MD&A)?

**Filters used:** ACN

**Answer:** [summary — structured comparison, found tone mismatch, 
cited both sections accurately]

**Citations checked?** Y — quotes traced to correct sections

**Did this change my thinking?** No — the mismatch it found (defensive 
in 1A, optimistic in MD&A) is structural to how 10-Ks are written, 
not diagnostic of ACN specifically.

**Would I have found this faster by reading the 10-K myself?** N/A — 
the question itself wasn't the right question to ask. The system 
answered it correctly; the problem was upstream in my question design.

**Question I wanted to ask but didn't:** 
- Compare AI risk factor language FY2025 vs FY2024 — what changed?
- Does MD&A acknowledge utilization/margin pressure from AI automation?

**Tag:** system worked, question wasn't diagnostic

## [2026-07-12] — ACN — MD&A vs 1A on AI utilization pressure

**Question asked:** Does MD&A acknowledge utilization/margin 
pressure from AI automation?

**Answer:** No — MD&A attributes margin compression to payroll 
costs, never mentions AI automation as a factor. Item 1A explicitly 
states AI will "adversely affect the utilization rate of our 
professionals." Management compartmentalizes the risk.

**Citations checked?** Y — margin discussion in Item 6/7, 
utilization language in Item 1/1A, both verified.

**Did this change my thinking?** Yes — the gap between what legal 
discloses and what management discusses in MD&A is wider than 
expected. Worth monitoring whether FY2026 MD&A starts acknowledging 
what 1A has said for two years.

**Would I have found this faster by reading the 10-K myself?** No. 
Cross-referencing margin drivers in MD&A against specific risk 
language in 1A would take 15-20 minutes of careful reading.

**Tag:** useful — first question where the tool surfaced a 
cross-section finding faster than manual reading


## [2026-07-12] — ACN — AI risk factor YoY comparison

**Question asked:** Compare AI-related risk factors FY2025 vs 
FY2024 Item 1A — what changed?

**Answer:** Three concrete additions in FY2025: (1) "ecosystem 
partners" and "AI-native companies" as new competitive threats, 
(2) explicit pricing/commercial model risk for AI solutions, 
(3) "pace and level of spending" qualifier on demand replacement.

**Citations checked?** Y — FY2025 and FY2024 Item 1 chunks both 
cited, language differences verifiable.

**Did this change my thinking?** Yes — the pricing-model risk 
language is new and specific. ACN is signaling that AI may 
compress per-unit pricing even if volume grows. Worth checking 
whether revenue-per-FTE or pricing metrics appear in the 
earnings call.

**Would I have found this faster by reading the 10-K myself?** 
No. Side-by-side comparison of two 10-K risk sections is exactly 
the kind of tedious cross-document work this tool should 
accelerate.

**Tag:** useful — cross-filing comparison, genuine time savings


## [2026-07-12] — ACN — Peer operating margin comparison

**Question asked:** How does Accenture's operating margin trend 
compare to a peer IT-services company's over the same period?

**Answer:** Provided ACN margins (FY2022-2025, both GAAP and 
adjusted), correctly declined to compare because no peer filings 
are in the corpus.

**Citations checked?** Y — margin figures from Item 6 across 
three filings.

**Did this change my thinking?** No — but the ACN-only trend 
(GAAP declining from 15.2% to 14.7% while adjusted holds at 
15.4-15.6%) is itself notable. The growing gap between GAAP 
and adjusted margins is driven by rising "business optimization 
costs" — worth investigating whether those are recurring.

**Would I have found this faster by reading the 10-K myself?** 
No — pulling 4 years of margins from 3 separate filings manually 
would take 10+ minutes.

**Question I wanted to ask but didn't:** N/A — next step is 
ingest a peer (CTSH) and re-ask.

**Tag:** partial — correct on ACN, limited by corpus scope


## [2026-07-12] — ACN vs CTSH — Operating margin comparison

**Question asked:** Compare Accenture's and Cognizant's operating 
margins for fiscal years 2023 through 2025, side by side.

**Answer:** Side-by-side table showing ACN GAAP/adjusted and CTSH 
GAAP/adjusted margins. Key finding: CTSH GAAP margin (16.1%) 
overtook ACN (14.7%) in FY2025 — a reversal. System flagged 
fiscal-year-end mismatch (Sept vs Jan) unprompted.

**Citations checked?** Verified CTSH 16.1% figure in citations.

**Did this change my thinking?** Yes — CTSH margin improvement 
relative to ACN is worth investigating. Is it sustainable or 
driven by one-time items?

**Would I have found this faster by reading the 10-K myself?** 
No — opening two companies' 10-Ks, finding the margin 
discussion in each, normalizing GAAP vs adjusted, and noting 
the fiscal-year mismatch would take 20+ minutes.

**Tag:** useful — cross-company comparison, genuine time savings, 
first question requiring named-entity decomposition to work

## [2026-07-13] — ACN — Revenue vs bookings growth divergence

**Question asked:** How has local-currency revenue growth trended 
over the last three fiscal years, and does that trend diverge from 
bookings growth over the same window?

**Answer:** Revenue growth: 8% → 2% → 7%. Bookings growth: 
5% → 14% → -1%. Opposite trajectories. System identified the 
structural explanation: Managed Services bookings (+24% in FY2024) 
convert to revenue over multiple years, explaining the lag.

**Citations checked?** Y — all figures from Item 6 across three 
filings.

**Did this change my thinking?** Yes — the bookings/revenue 
divergence and the Managed Services conversion lag are not obvious 
from reading any single filing. The system connected data points 
across three years and provided the structural explanation.

**Would I have found this faster by reading the 10-K myself?** 
No — pulling local-currency growth and bookings figures from 
three separate 10-Ks, then identifying the Managed Services 
conversion lag as the explanatory factor, would take 30+ minutes.

**Tag:** useful — cross-filing trend analysis with structural 
explanation, strongest output so far


## [2026-07-13] — AVGO — R&D/integration cost vs revenue growth

**Question asked:** Does R&D and integration-cost growth track 
segment revenue growth, or is growth being bought with 
disproportionate opex ramp post-VMware?

**Answer:** Growth is NOT being bought with opex ramp. Key findings:
- Infra Software R&D decreased despite 26% revenue growth 
  (VMware integration leverage)
- Integration/restructuring costs down 61%
- SG&A down 15% from headcount reductions
- Operating income +89% on +24% revenue (massive margin expansion)
- Caveat: SBC +33% (faster than revenue) — system flagged but 
  excluded from conclusion

**Citations checked?** verified SBC $7,568M figure

**Did this change my thinking?** Yes — the segment-level R&D 
breakdown (Semiconductor R&D +8% vs Software R&D -6%) shows 
VMware integration is producing real operating leverage, not 
just revenue stacking. More bullish signal than headline numbers 
suggest.

**Would I have found this faster by reading the 10-K myself?** 
No — this required pulling segment-level R&D from Item 8, 
integration costs from Item 7, SBC from the compensation note, 
and operating income by segment, then cross-referencing all 
against segment revenue growth. 45+ minutes of manual work.

**Question I wanted to ask but didn't:** How does AVGO's 
SBC-to-revenue ratio compare to peers (CTSH, ACN, IBM)?

**Tag:** useful — multi-section synthesis, segment-level 
granularity, strongest analytical output so far


## [2026-07-13] — AVGO — AI narrative vs reported numbers

**Question asked:** Did last year's MD&A AI-demand commentary 
show up in this year's reported segment revenue?

**Answer:** Semiconductor segment grew 22% revenue / 27% 
operating income, consistent with AI narrative. But: (1) no 
AI-specific revenue breakout exists — can't verify how much 
of the $6.8B increase is AI vs other lines, (2) system only 
retrieved FY2025 MD&A, not FY2024's forward-looking commentary.

**Citations checked?** Y — segment figures from Item 7/8 verified.

**Did this change my thinking?** Partially — the disclosure gap 
(AI asserted but unquantified) is itself a finding. The missing 
FY2024 comparison limits the answer's usefulness.

**Would I have found this faster by reading the 10-K myself?** 
Tie — the disclosure-gap observation is useful, but I'd still 
need to open the FY2024 10-K manually to do the actual comparison.

**Question I wanted to ask but didn't:** Rephrased version with 
explicit FY2024 vs FY2025 anchoring — about to try.

**Tag:** partial — correct on what's available, limited by 
single-filing retrieval on a cross-year question



## [2026-07-13] — AVGO — Export control risk factor YoY changes

**Question asked:** Has export-control/China risk-factor language 
changed materially year over year?

**Answer:** Yes, material escalation across three years:
- FY2023→FY2024: Huawei named disclosure dropped, "possible 
  decoupling" upgraded to "the decoupling"
- FY2024→FY2025: supply chain risk added (previously only 
  customer-side), restricted entity list language expanded to 
  include manufacturing impact, regulatory scrutiny broadened 
  from Korea-only to Korea/Japan/EU

**Citations checked?** Y — Huawei appears only in chunk 5171 (FY2023 filing, 2023-12-14), absent from all FY2024 and FY2025 chunks. Confirmed.

**Did this change my thinking?** Yes — the progressive escalation 
pattern (hypothetical → declarative → supply-chain-wide) suggests 
management's internal risk assessment is materially worsening 
each year, even as MD&A frames AI demand as a tailwind. Same 
1A-vs-MD&A tension pattern as ACN, but with concrete textual 
evidence of escalation.

**Would I have found this faster by reading the 10-K myself?** 
No — comparing risk-factor language across three separate 10-Ks 
is exactly the kind of tedious cross-document work that takes 
30-45 minutes manually. This is the tool's strongest use case.

**Tag:** useful — cross-filing textual diff, strongest analytical 
output, portfolio-quality example