# Trading agent — known gaps (documented, not closed)

Residual issues that are understood and deliberately left open. Each entry
says why it isn't fixed here and what would close it. Remove entries only
when actually closed, not when they become inconvenient.

## Phase 4 — News/Sentiment (logged 2026-08-21)

1. **Article bodies are not point-in-time bounded.** Finnhub returns each
   article as it exists *now*. A piece published before the probe date may
   have been updated after it (corrected figure, revised headline, appended
   "UPDATE:" paragraph); the publish-date filter cannot see this. A genuine
   residual lookahead channel, not fixable without a point-in-time news
   archive. (Inference about how Finnhub serves content — not verified
   against their docs.)

2. **Summary faithfulness is unverified.** The index-join in
   `news_digest_port.py` guarantees the metadata is real; nothing checks
   that Haiku's one-line summary accurately represents the article body.
   Lower stakes than the fundamentals numbers, but it is a fabrication
   surface with no verifier. Closing it would need a second model call per
   article, which isn't worth it at this node's stakes.

3. **Truncation is a sampling bias, not just a cap.** `MAX_ARTICLES=60`
   sorted newest-first means a busy week silently drops older-but-possibly-
   more-important coverage. `truncated_by_cap` makes it visible (and should
   surface in the Phase 7 memo as a caveat); it doesn't make it correct.

   *Measured on the first live run (MSFT, 2026-08-21):* Finnhub returned
   **247 articles** for a 14-day window. The cap kept 60 and dropped 187,
   collapsing the effective window from 14 days to **5 days**
   (2026-08-17..08-21). Worse, 2026-08-13 alone had **101 articles** — an
   obvious event spike — and the cap discards that entire day. For a
   mega-cap the cap is not a safety valve, it is the dominant sampling
   decision. Consider a per-day quota or event-aware selection rather than
   a flat newest-first cut.

   *Also measured:* dedup removed **0 of 247**. The guide expected
   syndicated reprints to be a large share; across Yahoo/Benzinga/
   SeekingAlpha the headlines differ enough that exact-headline dedup never
   fires. Dedup is cheap and harmless, but it is not the cost lever it was
   assumed to be — the cap is.

4. **News is single-vendor.** Phase 3's price fetch has a yfinance/Finnhub
   router; news has no fallback, so a Finnhub outage kills the node.
   Acceptable for now — but `VendorError` from this node needs a decided
   policy in Phase 7: does the pipeline halt, or produce a memo flagged
   "news unavailable"? Decide explicitly rather than discovering the
   default.

5. **Finnhub's `company-news` feed is mostly not about the company.**
   Found on the first live run, not anticipated in the design. For MSFT
   (2026-08-21, 60 articles reaching the digest):

   | Article relates to Microsoft how | Count |
   |---|---|
   | Named in the headline | 6 (10%) |
   | Body/adjacent mention only (AI, OpenAI, Azure…) | 9 (15%) |
   | No Microsoft signal at all | 45 (75%) |

   Finnhub tags **all 60** with `related: "MSFT"`, so that field is useless
   as a relevance filter. The dropped-in articles are real news about other
   companies — Ferrari, Alibaba, Walmart, Netflix, McDonald's — plus 13F
   trackers and index-movers columns. FIG showed the same pattern more
   mildly (7 of 15 headlines named Figma).

   The consequence is direct: `SentimentSummary.net_score` for MSFT
   (+0.183) is largely a measure of **AI-sector sentiment**, not Microsoft
   sentiment, and Phase 5's debate would consume it as the latter. This
   needs a decision before the debate nodes rely on it. Options, cheapest
   first: (a) require the ticker/company name in the headline, (b) score
   relevance in the same Haiku call already being made and filter on it,
   (c) weight the aggregate by relevance instead of filtering. Each trades
   recall for precision — (a) would drop legitimate stories that never name
   the company, which for a mega-cap may be a large share of what matters.

6. **[Phase 3 residual] The price fetch is not `as_of_date`-bounded.**
   `technical_node` fetches ~1 year of history with no upper bound and
   derives its `as_of_date` from `df.index[-1]`. Now that `as_of_date`
   lives in `TradingState`, a probe run (`--as-of 2025-03-01`) gets news
   bounded at March 2025 alongside price data through today — a real
   lookahead hole in any historical probe. Fix when historical backtesting
   is actually needed, not before.
