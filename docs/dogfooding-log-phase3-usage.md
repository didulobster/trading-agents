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