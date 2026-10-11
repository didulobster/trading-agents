# Two bounded contexts in one package, joined by one entry point

EDGAR Research (ingestion, retrieval, `/ask`, the Research agent) and Trading (the multi-agent pipeline) are split into two bounded contexts inside one Python package, `app/edgar_research/` and `app/trading/`, each owning its own glossary and docs, with the LLM providers, pricing, cost logging, config and vault in a shared kernel at `app/shared/`. Trading may reach EDGAR Research only through one published entry point that returns a fundamentals memo, and EDGAR Research never imports Trading; a test enforces both rules. We wanted each side to own its architecture and language without paying the packaging cost first, since trading previously reached into the Research agent through about six internal symbols.

## Considered Options

- **Two git repos**: the cleanest separation, but it needs the seam narrowed and a release process before anything else can happen.
- **A `uv` workspace with two packages**: dependencies are enforced by the packaging, but it's the same untangling cost up front. It's still the natural next step if the boundary test keeps holding.

## Consequences

- The Research agent belongs to EDGAR Research, not Trading. Trading's fundamentals analyst translates a fundamentals memo into its own fundamentals report at the seam.
- `/news-assess` belongs to EDGAR Research. It runs the Research agent and has nothing to do with Trading's news digest. (2026-10-11: the endpoint was later removed for having no caller; news assessment is now CLI-only, via `researcher --news`.)
