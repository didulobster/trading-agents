# Context Map

## Contexts

- [EDGAR Research](./app/edgar_research/CONTEXT.md): ingests SEC filings into a corpus and answers questions over it, up to a full fundamentals memo
- [Trading](./CONTEXT.md): analysts, debaters, a risk panel and synthesis turn a ticker into a decision memo

## Relationships

- **Trading → EDGAR Research**: Trading's fundamentals analyst asks the Research agent for a fundamentals memo; that is the only edge between the two
- **Both → shared kernel**: LLM providers, pricing, cost logging, config and the vault; its only domain term is Vault

## Shared language

**Vault**:
Where every run's artifacts land, one folder per run, whichever context produced them.
_Avoid_: output dir, results
