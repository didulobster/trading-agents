# Using EDGAR Research for real research

EDGAR Research answers questions about a company **from its SEC filings, with citations
you can check**. Treat it as a fast, cited first pass over the filings — never as the last
word. Commands and endpoints are listed in [../README.md](../README.md); how it works is in
[architecture.md](./architecture.md).

## What it is good for

| You want… | Use |
|---|---|
| A forensic first read of a company | `researcher TICKER` — a 12-item checklist memo (free cash flow, risk-factor changes, MD&A shifts, stock comp, segments, debt, contingencies, customer concentration, buybacks, internal controls, earnings quality, backlog), with red flags and data gaps |
| One specific question ("what drove gross margin down?") | `POST /ask` — a grounded answer, every claim cited like `[AVGO 10-K 2025 §Item 7]` |
| A headline checked against your thesis and the filings | `researcher TICKER --news "…"`, using your notes in `watchlist.yaml` |
| What is new on EDGAR | `POST /latest-filings`, or `cli corpus-status` |

## A workflow

1. **Ingest the annual reports deliberately.** Left to itself the agent ingests only a few of
   the newest filings: a cold AVGO run on 2026-10-11 took one 10-Q and two 8-Ks, so its memo
   had no 10-K to work from and listed the annual-report items as data gaps.

   ```bash
   uv run python -m app.edgar_research.cli ingest AVGO --type 10-K --limit 2
   uv run python -m app.edgar_research.cli ingest AVGO --type 10-Q --limit 4
   uv run python -m app.edgar_research.cli corpus-status --ticker AVGO --verbose
   ```

   Check `corpus-status`: a filing can be `EMBEDDED` with far too few chunks.

2. **Start the server and run the memo.**

   ```bash
   uv run uvicorn app.main:app
   uv run python -m app.edgar_research.agent.researcher AVGO 2>/dev/null > avgo.md
   ```

   A memo costs cents to about $0.45; the AVGO run above cost $0.07. It is also saved to
   the vault as `$HOME/$MEMO_DIR/<TICKER>/<TICKER>-<timestamp>.md`, next to a `-provenance.md` with every
   tool call and result the memo was built from.

3. **Drill into what the memo flags** with `/ask`, one narrow question at a time.

4. **Verify before relying on anything.** Each claim's citation names the filing and
   section, so checking it against the source is quick.

## How far to trust it

- **Reliable:** figures retrieved from a filing and cited, and arithmetic done by the
  `calculate` tool.
- **Spot-check:** period labels (which quarter, which fiscal year) and causal explanations
  ("revenue fell *because*…").
- **Read the appended sections first.** The verifier adds them to the end of the memo when
  it finds something:
  - **Verdict Inconsistency** — the Executive Summary and the Assessment state different
    verdicts. An audit on 2026-09-12 found this in 7 of 34 vault memos; resolve it against
    the Assessment's findings before acting on either.
  - **Unverified Figures and Quotations** — numbers or quotes not found in the retrieved text.
  - **Unbacked Derivations** and **Underived Arithmetic** — computed figures without a
    traceable calculation.
- **Data Gaps are unknowns, not clean results.** Something the agent could not retrieve may
  still be in the filing.
- **Ask one thing at a time.** A three-part question can miss a chunk that the same
  question asked alone ranks first (measured on ACN's FY2025 10-K, 2026-09-12).
- **`--as-of` bounds what it can read, not what the model knows.** A historical run cannot
  retrieve later filings, but the model may still remember how the period turned out.

## What it cannot do

- **Filings only.** No prices, valuation multiples, guidance, consensus estimates or call
  transcripts.
- **Not a rating.** Every memo says so: "Input to an investment decision, not a rating."
  The Trading context turns memos into decision memos, as a research experiment, not advice.

The simplest real use: run it on a company before reading the 10-K yourself, then go into
the filing knowing which sections matter, which numbers to check and what is missing.
