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

3. **[Largely resolved] Truncation is a sampling bias, not just a cap.**
   A newest-first cap means a busy week silently drops older-but-possibly-
   more-important coverage. `truncated_by_cap` makes it visible (and now
   surfaces in the vault sentiment report as a caveat); it doesn't make it
   correct.

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

   **[Resolved 2026-08-22] `MAX_ARTICLES` raised 60 → 300.** Relevance
   scoring (gap 5) had made the cost of the old cap precise: of MSFT's 247
   in-window articles, 58 named Microsoft and the cap kept **6** of them,
   leaving a signal that was correct but too thin to use (three of the six
   were near-identical "Microsoft Versus Competitors" template pieces).

   300 is derived from the budget rather than picked for roundness. Worst
   case is ~$0.00042/article plus a 496-token system prompt per batch, so a
   full-cap run costs ~$0.136 — about 68% of `NEWS_BUDGET_USD`. That
   ordering matters: the budget assertion fires only *after* the batches are
   paid for, so it can never refund a run it fails. Keeping the cap strictly
   inside the budget means volume degrades to flagged truncation instead of
   an exception charged at full price.

   *Verified live (MSFT, 2026-08-22):* 248 articles fetched, **248 in the
   digest**, `truncated_by_cap=False`, 11 distinct days covered instead of
   5, and **54 primary articles instead of 6**. net_score +0.407 over n=54.
   Cost $0.0997 (50% of budget); measured $0.000402/article, within 0.3% of
   the AVGO figure the estimate was built on. Wall clock 24.7s for 17
   batches at concurrency 5 — the batches were made concurrent in the same
   change, since 20 sequential calls would otherwise have put the node into
   the minutes.

   *Residual:* a ticker with more than 300 in-window articles still
   truncates, still newest-first, and still flags it. The rejected
   alternative was prioritizing likely-relevant articles before the cap,
   which keeps cost flat but needs the company *name* — matching the ticker
   alone found only 8 of MSFT's 58, because headlines say "Microsoft", not
   "MSFT" — so it requires a name lookup (e.g. Finnhub `/stock/profile2`)
   plus a cache. A per-day quota instead of a flat newest-first cut remains
   the cheapest way to stop an event day being dropped wholesale if the cap
   ever binds again.

4. **News is single-vendor.** Phase 3's price fetch has a yfinance/Finnhub
   router; news has no fallback, so a Finnhub outage kills the node.
   Acceptable for now — but `VendorError` from this node needs a decided
   policy in Phase 7: does the pipeline halt, or produce a memo flagged
   "news unavailable"? Decide explicitly rather than discovering the
   default.

5. **[Addressed] Finnhub's `company-news` feed is mostly not about the
   company.** Found on the first live run, not anticipated in the design.
   For MSFT (2026-08-21, 60 articles reaching the digest) 75% had no
   Microsoft signal at all — Ferrari, Alibaba, Walmart, Netflix,
   McDonald's, 13F trackers, index-movers columns — yet Finnhub tagged
   **all 60** with `related: "MSFT"`, so that field cannot filter.

   Two causes, both now fixed. The prompt never named the company, so the
   model scored each article against whichever company it was about; the
   batch now leads with `COMPANY UNDER ANALYSIS`. And there was no way to
   separate company news from sector news, so `NewsItem.relevance`
   (primary/mentioned/unrelated) is scored in the same call and
   `sentiment_node` aggregates only `AGGREGATED_RELEVANCE`.

   Residual, worth knowing: LLM relevance agreed with a plain
   "does the headline name the company" check **6/6 on MSFT and 10/10 on
   FIG**, with no disagreement either way. So for the current primary-only
   policy the model is not yet earning its keep over a free regex — it is
   free (same call), but the judgement it uniquely adds lives in the
   `mentioned` tier, which nothing currently consumes. If Phase 5 wants
   sector context as a separate signal, that tier is where it is.

6. **[Phase 3 residual] The price fetch is not `as_of_date`-bounded.**
   `technical_node` fetches ~1 year of history with no upper bound and
   derives its `as_of_date` from `df.index[-1]`. Now that `as_of_date`
   lives in `TradingState`, a probe run (`--as-of 2025-03-01`) gets news
   bounded at March 2025 alongside price data through today — a real
   lookahead hole in any historical probe. Fix when historical backtesting
   is actually needed, not before.

## Phase 5 — Bull/Bear Debate (logged 2026-08-23, updated 2026-08-24)

**Exit criteria: all three met.** Five full pipeline runs (AVGO, ACN, FIG,
ASML, MSFT), fresh thread ids, every one terminating at `round_cap` with
contiguous indices, strict alternation and cost under budget; both
forced-crash resume variants pass. Debate cost $0.077–$0.094 per run against
a $0.35 ceiling. What follows is what those runs revealed *about the quality
of the debate*, which the exit criteria do not test.

1. **A crash in the first moments of a super-step loses the previous turn's
   completed work.** Found by running the two forced-crash resume tests
   (AVGO, 2026-08-23), and it contradicts what the Phase 5 design note
   predicted.

   | crash point | turns committed | on resume |
   |---|---|---|
   | at node entry for turn 2 (variant A) | **1** | turn 1 re-run |
   | after the LLM call for turn 2 (variant B) | **2** | turn 2 re-run |

   In variant A the log shows turn 1 completing and printing, yet the
   checkpoint holds only turn 0 and `snap.next` is `('bear_turn',)`. The
   previous super-step's write was still pending when the process died. In
   variant B the ~2-second LLM call gave that commit time to land, so turn 1
   survived. **The last checkpoint can therefore lag one turn behind the last
   COMPLETED turn** — "resumes from the last per-round checkpoint" holds, but
   the last checkpoint is not always the last thing you saw on screen.

   Consequences, none of them corruption: the resumed transcript is
   contiguous and correct every time, and the cost is exactly one wasted LLM
   call per crash ($0.0074 measured, logged as a normal `trading-debate-*`
   entry, so the spend is visible but indistinguishable from a kept turn).
   The design note's variant-A assertions (`len(debate_turns) == 2`,
   `snap.next == ("bull_turn",)`) are wrong for this setup and should not be
   written as a regression test.

2. **Convergence is mitigated, not eliminated.** The §5 guardrails raise the
   cost of unjustified agreement — a concession must name a real opposing
   `claim_id`, a claim must quote the report it cites, a figure must appear
   in the evidence pack — but they cannot make two instances of one base
   model independent. They share priors. A transcript where both sides
   converge on a correct conclusion and one where they converge from shared
   bias are indistinguishable from inside the transcript.

3. **The number guard has an unmeasured false-positive rate.** Containment
   plus a precision-scoped rounding clearance plus the Phase 3 percent
   transforms. Three classes found and closed so far, each from live output:
   rounding ("RSI of 41.2" for 41.2033), percent-against-percent, and
   hyphenated compounds ("the low-30s", "sub-50-SMA" read as -30 and -50).
   Expect more — "roughly $12B" for 12.2, unit changes. Until measured, a
   non-empty `guard_flags` means *review*, not *fabricated*.

   *Measured (AVGO, 2026-08-23, 6 turns over the technical report alone):*
   6 flags, of which 4 were the same derived figure and 2 were the hyphen
   bug. So **1 distinct true positive and 1 distinct false-positive class**,
   and the guard is currently dominated by arithmetic the debaters do on
   pack values — 368.45 − 368.30 = 0.15, correctly flagged under "cite,
   don't compute", but benign on inspection. Watch whether that shape
   trains readers to skip the flags; if it does, the answer is a separate
   "derived from pack values" category rather than dropping the rule.

4. **Almost nothing is ever conceded or sharpened.** Across **five full
   pipeline runs, 30 turns**: 29 `hold`, 1 `sharpen`, **0 `concede`**. The
   §5(a) guard makes an *unjustified* concession structurally impossible, but
   nothing makes a justified one attractive, and total entrenchment is as
   uninformative as convergence — it just fails in the opposite direction.

   The single `sharpen` (FIG, turn 3) is the one piece of evidence the stance
   field is not dead weight. The concession guard has still never fired in
   production, so its correctness rests entirely on unit tests.

   **[Investigated 2026-08-24, falsified] Read against claim volume, this
   looked like it might be worse than "rare concessions": 145 claims / 30
   turns = 4.83 per turn against a `max_length=5` cap — the schema is binding
   on nearly every turn. Put beside 145/145 distinct ids and 0 concessions,
   the hypothesis was that each side mines fresh claims from a 37k–44k-char
   pack indefinitely without ever contesting the other — two analysts
   writing in alternation, not a debate.**

   Checked directly rather than argued: for every turn 1–5 across all five
   transcripts, does `rebuts` resolve to a claim actually made in the
   opponent's immediately preceding turn? **95 of 95 do — 100%, independently
   across all five tickers (14–24 each), 0% of turns with empty `rebuts`.**
   That is the strongest form of engagement available to check (the
   *previous* turn specifically, not just some opposing claim anywhere in
   the transcript) and it is fully satisfied. The hypothesis is falsified:
   the claim cap is real and forces volume, but genuine engagement is
   happening underneath it, not instead of it.

   `rebuts` itself was unvalidated when this was checked — nothing stopped a
   turn from naming a hallucinated or own-side id, so the 95/95 result could
   only be trusted because it was measured directly against the raw
   transcripts. **Closed 2026-08-24**: `check_rebuts` now enforces the same
   structural requirement `check_concession` enforces for `concession_trigger`
   — every rebutted id must be a real claim belonging to the opposing side.
   Same reasoning as (a): a turn that fails this should raise, not pass
   silently, because an unvalidated `rebuts` makes "theatre that looks
   adversarial" possible even though this batch shows it did not happen.
5. **Debate quality is now tied to `LLM_CLAUDE_MODEL`, and Haiku 4.5 makes
   analytical errors Sonnet 5 did not.** `DEBATE_MODEL` follows the
   project-wide setting as of 2026-08-23. Mechanically Haiku is fine — no
   retries, valid payloads, `claim_id` reuse, `rebuts` populated, ~$0.005 a
   turn against Sonnet's ~$0.025.

   *But on the first two live Haiku turns, BOTH sides called an RSI of 38.7
   "oversold".* It is not — oversold is below 30, and Phase 3's
   `derive_relations` says so in as many words ("NEITHER overbought nor
   oversold"). `guard_flags` was empty for both turns, because every number
   was real. The error is in the reasoning, and nothing in this phase
   catches that.

   **[Mitigated 2026-08-23]** The pack rendered the indicators as raw JSON
   and threw `derive_relations()` away — the very block Phase 3 added because
   a model asked to compare indicator values itself gets it wrong. It is now
   the first thing in the technical section, marked authoritative, with a
   matching rule in the system prompt. *Re-verified live on the same
   indicators, twice:* both sides now write "neither overbought nor
   oversold", and the RSI claim id changed from `avgo-rsi-oversold` to
   `avgo-rsi-neutral`.

   *Residual, and the reason this stays on the list:* only the relations that
   `derive_relations` computes are protected — price vs the two SMAs, the
   SMAs against each other, MACD vs signal, the RSI band, the Bollinger
   position, volume vs its average. Any other comparison a debater makes is
   still its own unguarded reasoning, and nothing downstream re-verifies it.
   The general point stands: a cheaper model buys a transcript that can look
   like a debate and be wrong on the facts, so read one by hand after any
   model change — the exit criteria test termination and resume, not
   argument quality.

6. **[Mitigated 2026-08-23] `evidence_quote` is a single contiguous span,
   but technical evidence often is not.** A claim like "price is above its
   200-day average" rests on two fields that sit apart in the JSON, so an
   honest citation of both was a splice and got flagged. Both live models did
   it — Sonnet with an ellipsis, Haiku with a comma.

   The relations block fixed this as a side effect: one relation line carries
   both values *and* the comparison between them, so it quotes cleanly.
   *Measured on the same two Haiku turns:* `unquoted_evidence` went from 4/4
   and 3/5 claims to **zero on both turns**.

   *Residual, and bigger than expected. Measured on the first FULL-pack run
   (AVGO, 2026-08-23, all four reports, 61k-char pack, 25 claims):*

   | source | claims | unverified | rate |
   |---|---|---|---|
   | fundamentals | 17 | 7 | **41%** |
   | news | 1 | 0 | 0% |
   | none | 7 | 0 | — |
   | technical | **0** | 0 | — |

   Every one of the 7 is a true positive on inspection: three are explicit
   `...` ellipses, one joins a section header to a table row, and three are
   verbatim for 88 of 112 characters and then append a clause ("which
   exceeds the 20pp threshold") that is nowhere in the memo. The guard is
   working; the model cannot reliably quote long prose.

   Note the technical row: **zero technical claims**, so this run did not
   exercise the relations block at all. The 4/4 → 0 improvement measured on a
   technical-only pack says nothing about a full one. A fundamentals memo is
   23k characters of prose and it crowds everything else out.

   Allowing a list of quotes per claim remains the real fix, and it now looks
   necessary rather than nice: at 41% the caveat "7 claim(s) cite a report but
   the quoted span is not in it" is the memo's loudest debate signal.

   *Second full-pack run, and a different failure SHAPE, not just a bigger
   rate (FIG, 2026-08-24, `MOCK_FUNDAMENTALS=1`, 30 claims):*

   | source | claims | unverified | rate |
   |---|---|---|---|
   | fundamentals | 23 | 14 | **61%** |
   | news | 1 | 0 | 0% |
   | none | 6 | 0 | — |
   | technical | **0** | — | — |

   AVGO's failures were ellipsis-splices and header-to-table joins — two
   adjacent-but-not-contiguous prose spans stitched together. FIG's cached
   fundamentals report is unusually table-dense, and the failures there are a
   different shape: the debater assembles a summary SENTENCE out of several
   separate table fields and presents it as one verbatim quote —

   > "Free Cash Flow \$242.7M FY2025 FCF Margin 23.0% Figma Q2 2026 revenue
   > reached \$370.1M, up 48%"

   — three unrelated facts from three places in the memo, formatted as prose
   and cited as a single `evidence_quote`. Spot-checked with the same
   longest-verbatim-prefix method as the AVGO run; none of the 14 clear that
   bar past a few dozen characters, so these are true positives, not
   normalization gaps.

   Two full-pack runs now, two different source documents, two different
   failure shapes, both driven by the same root cause: **the model is not
   trying to quote, it is trying to summarize, and `evidence_quote` gives it
   nowhere honest to put a summary.** That strengthens the case for a
   structured citation (a list of short verbatim spans plus a separate
   `synthesis` field the guard does not check) over patching this guard
   further — the current one-contiguous-span field is fighting what the
   model naturally wants to produce, on prose AND on tables.

7. **Containment cannot catch a correctly-quoted figure used wrongly.**
   Right number, wrong period or wrong entity. Same period-consistency gap
   `ask_edgar` has, now one layer further downstream.


   **[Related, closed 2026-08-24] Containment on the raw indicators JSON was
   worse than merely unable to catch a period/entity mismatch — it made a
   fully ungrounded citation LOOK grounded.** `evidence_quote` passing
   verbatim on `macd_histogram":0.3556307403914323` satisfies containment,
   because that exact string is in the pack, but it is the debater grepping
   the serialized indicator dict rather than citing anything the analyst
   said. Found live (ACN, technical-only pack, 2026-08-24): 3 of 4 technical
   citations in one debate did exactly this. `quotable_texts` now excludes
   the raw JSON from the corpus `check_quotes` validates against — the
   `derive_relations` sentences and the interpretation prose remain
   quotable, since those are genuinely something the analyst said, and
   `build_evidence_pack` (the number-fabrication guard's corpus) is
   unaffected, so a faithfully-copied full-precision figure in argument
   prose is still not falsely flagged as fabricated. All three raw-JSON
   citations in the transcript that surfaced this now fail the quote check.
8. **[Closed 2026-08-24] `UNPRODUCTIVE_STOP` was structurally dead, and has
   been removed.** It needed BOTH of two consecutive turns to have zero new
   `claim_id`s. Across every full-pack run, at most ~25% of a turn's claims
   were ever reused; the direct trigger case — turn 5 in a technical-only ACN
   debate reused 1 of 4 ids and still scored `productive=True`, because the
   other 3 were new — confirms the conjunction the branch needed never comes
   close to occurring. `MAX_ROUNDS` is now the ONLY termination lever, stated
   as such in `debate_router.py`'s module docstring rather than left implicit.
   `DebateTurn.productive` and `is_productive` are kept as an observational
   signal (cheap, still an honest per-turn reading, still rendered in the
   vault transcript) — only the router clause that treated it as a
   termination signal is gone. If restatement-heavy behavior is ever observed
   for real (a different model, a much larger `MAX_ROUNDS`), reintroduce a
   ratio-based version calibrated against the transcript that showed it, not
   against a guess — no debate to date shows what a genuinely-exhausted
   argument looks like in terms of new-claim ratio, because the round cap
   always arrives first.

9. **[Closed 2026-08-24] `claim_id` reuse carried no guarantee the reused id
   named the same claim.** `acn-volume-deteriorating` appeared in turn 3
   ("collapsing conviction that exposes recovery moves to reversal risk") and
   turn 5 ("deteriorating participation that undermines recovery conviction")
   of one debate — one id, two different assertions. Anything aggregating by
   `claim_id` — Phase 6's risk debate is the reason this matters — would
   silently keep whichever occurrence it read last.

   Two changes, not raising: `check_claim_stability` flags a reused id whose
   text disagrees with its FIRST occurrence onto `DebateTurn.claim_text_drift`
   (surfaced in the memo caveats and the vault transcript, not blocked — a
   model paraphrasing the same point differently across turns is expected,
   and rejecting every wording change would make claim_id reuse impractical).
   `canonical_claims(turns)` in `domain/debate.py` is the actual safety
   mechanism: it returns one `DebateClaim` per id, always the first
   occurrence, and is the function any future aggregation should read
   through instead of flattening `claims` across turns and indexing by id
   directly. Verified against the real transcript that surfaced the bug: the
   fix detects exactly the one drifted id, and `canonical_claims` returns
   turn 3's wording as authoritative for `acn-volume-deteriorating`.

10. **[Partly addressed] The debate barely uses the news evidence, and
   barely uses the technical report at all.** Citations across five full
   runs, 145 claims:

   | source | claims | share | unverified |
   |---|---|---|---|
   | fundamentals | 118 | 81% | 28% |
   | none (reasoning) | 16 | 11% | — |
   | news | 9 | 6% | 22% |
   | **technical** | **2** | **1%** | 50% |

   The fundamentals memo dominates the argument regardless of what else is in
   the pack. Note the technical row: the `derive_relations` block added to fix
   the "RSI 38.7 is oversold" error is **almost never exercised on a full
   pack** — 2 citations in 145 — so that fix is verified only on
   technical-only runs.

   The pack trim helped the *cost* side conclusively. MSFT carried 247 news
   items into a 44,073-char pack, while pre-trim AVGO carried 188 into
   61,346. It did not measurably move citation share.

   Ordering, length-balancing, or per-source claim quotas remain plausible;
   none is obviously right. The primary-article count is also still unbounded
   — the only cap upstream is `MAX_ARTICLES=300` on the digest.

   **[Settled 2026-08-24] Is technical being starved, or is the report just
   short?** The latter. Measured pack share vs citation share, summed across
   all five transcripts:

   | source | pack share | citation share |
   |---|---|---|
   | fundamentals | 76.7% | 81% |
   | technical | **4.5%** | **1.4%** |

   Both track their pack share closely — fundamentals slightly over,
   technical slightly under, neither by much. There is no disproportionate
   crowding-out to fix in the debate pack or the trim. Phase 3 caps the
   technical interpretation at 3–5 sentences plus one JSON block; a
   multi-page fundamentals memo will out-cite that at roughly its size
   regardless of ordering or quota. If more technical grounding in the
   argument is wanted, the lever is Phase 3's output length, not Phase 5's
   pack construction — a separate decision, not made here.
11. **Order bias is unquantified.** Bull speaks first and bear gets the last
   rebuttal in each round. Full mitigation doubles cost. Run one ticker
   bear-first by hand, compare the surviving claim sets, and put the number
   here before building any machinery.

12. **Nothing downstream re-verifies debate output.** `memo_verifier` runs
   inside `run_agent`; the debate never calls it. The number guard is the
   only check between a fabricated debate figure and the memo.

13. **The memo does not yet render the debate.** `bull_case`/`bear_case` are
   still "STUB" — Phase 7's job. Phase 5 delivers the transcript to the
   vault and the *caveats* to the memo, so a capped or skipped debate is
   visible; the argument itself is not.

14. **The model cannot emit an empty string into a tool call.** Asked for one
   it writes a stray `</antml parameter>` marker instead, which landed in
   `concession_trigger` on 4 of 4 live turns and tripped the concession
   guard on turns that conceded nothing. Worked around with a `'none'`
   sentinel normalized back to `""` in `domain/debate.py`. Undocumented
   behaviour, found live — if a future model stops doing it the workaround
   is harmless, but the sentinel is load-bearing today.

15. **Strict tool schemas cost the count bounds.** `strict: true` was needed
   to stop the model flattening the payload (DebateClaim fields hoisted to
   the top level, `stance` missing, on 3 of 3 turns), and it rejects
   `minItems`/`maxItems`. The 1..5 claim bound now reaches the model only as
   prose in the field description; pydantic still enforces it on the way in,
   so a violation costs the one retry rather than passing.

16. **[Closed 2026-08-25, Phase 6 Gate C] `technical_node` derived `as_of_date`
    from `df.index[-1]` and ignored `state["as_of_date"]`** (Phase 4 gap 6).
    The debate is the first node to read all four reports side by side, so it
    was the first place a mixed-vintage evidence pack could produce a
    confidently wrong argument.

    *Observed (AVGO, 2026-08-23):* the run was invoked `--as-of 2026-08-20`
    and the technical report came back `as_of=2026-08-21`. Six debate turns
    then argued in detail over a last close and a set of moving averages
    from **the day after the run's stated bound**, and the memo is dated
    2026-08-20. Nothing in the memo said the price evidence was from a later
    date. Not a Phase 5 bug, but Phase 5 is where it stopped being
    theoretical: the debate spent its entire transcript on a 0.15-point
    margin that belonged to a bar the run was not supposed to see.

    **Fix:** `get_price_history(ticker, as_of)` now takes `as_of` and fetches
    a 400-day trailing window ending there instead of `period="1y"` anchored
    at wall-clock now; both vendor helpers bound their own result
    (`_bound_to_as_of`) and `get_price_history` re-asserts the bound as a
    belt-and-braces check, the same posture as `news_node`'s lookahead
    post-assert. Verified two ways: a unit test mocking the yfinance SDK
    boundary (not `_try_yfinance` itself) so the real bounding path runs
    end-to-end through `technical_node`, and live (MSFT, 2026-08-25,
    `--as-of 2026-08-24`) — `bars=276`, technical report `as_of=2026-08-24`,
    exactly the requested bound.

## Phase 6 — Risk Panel + Synthesis (logged 2026-08-25)

**Exit criteria: 1, 3, 4, 5, 7 verified by test (no live run needed for these
— see §1 of the Phase 6 plan). Criteria 2, 6, 8 verified by one live run**
(MSFT, technical-only, `--as-of 2026-08-24`) rather than the five-ticker
sweep Phase 5 used — this phase's own code changes nothing about
fundamentals/news, so a single run against a real model was enough to prove
the two new cycles (risk panel, synthesis) actually work end to end; it is
not the same statistical confidence Phase 5's five-run sweep gives its own
exit criteria, and should not be read as such.

Measured: 6 risk turns terminated by `round_cap`, 5-factor ledger (1
contested), 6 debate turns terminated by `round_cap` (unchanged Phase 5
behavior), synthesis resolved every citation on the first attempt (no
reference-retry needed), zero fabrication blocks. Cost — debate $0.0441,
risk panel $0.0697, synthesis $0.0120, technical $0.0016; total $0.128
against Haiku 4.5 pricing (the project's current `LLM_CLAUDE_MODEL`), well
under both `RISK_BUDGET_USD`/`SYNTHESIS_BUDGET_USD` ($0.20 each) and the
plan's $0.30 combined ceiling. The plan's §10 estimate ($0.19-0.22) was built
on Sonnet 5 pricing ($3/$15); Haiku 4.5 ($1/$5) tracks proportionally lower,
consistent rather than a surprise.

1. **[Closed 2026-08-25, found before any live run] Anthropic's strict tool
   schema rejects `minimum`/`maximum` on integer properties, not only the
   array/string bounds (`minItems` etc.) Phase 5 anticipated.** `RiskScore`'s
   `severity`/`likelihood` (`ge=1, le=5`) 400'd the first risk-panel API call
   with `"For 'integer' type, properties maximum, minimum are not
   supported"`. `debate_port._STRICT_UNSUPPORTED` (shared by risk_port and
   synthesis_port through `_inline_refs`) now strips `minimum`/`maximum`
   too; the 1-5 range reaches the model only as prose
   (`domain/risk.py`), pydantic still enforces it on the way back in — same
   pattern as the claim-count bound Phase 5 already handles this way.
   Caught by the test suite hitting a real API call before this was fixed
   (~$0.06 of avoidable spend, now fixed with every port's LLM calls mocked
   in tests going forward — see `tests/agent/trading/test_debate_graph.py`,
   `test_checkpoint_roundtrip.py`, `test_news_nodes.py`).

2. **[Closed 2026-08-25, found on the one live run] The risk panel's own
   number-fabrication guard didn't recognize a number the panel itself had
   already established.** RF03's trigger ("RSI falls below 60"), proposed at
   turn 0 and shown to every later turn in the prompt
   (`render_risk_transcript`), was flagged `unbacked_number: 60` when turns
   3-5 legitimately cited it back — the guard's corpus (`_check_turn`'s
   `number_corpus`) was reports + debate only, never the risk panel's own
   running transcript. Fixed by adding `render_risk_transcript(turns)` (prior
   turns only — a turn cannot back itself) to the corpus. Two regression
   tests added (`test_risk_port.py`) reproducing the exact live shape: a
   later turn citing an earlier turn's trigger number, and a later turn
   citing an earlier turn's own severity/likelihood score.

   *Residual, left as-is because it matches Phase 5's own documented
   precedent* (known-gaps item 3, "arithmetic the debaters do on pack
   values, correctly flagged... but benign on inspection"): the same live
   run's turn 4 flagged `4.54` — a genuinely COMPUTED value (64.54 RSI minus
   the 60 trigger threshold) that never appears verbatim anywhere upstream.
   That is a true positive under "cite, don't compute," not a bug.

3. **Gate A's design pivot (Python-assigned `factor_id`) is confirmed by the
   one live run, not just by the historical debate transcripts.** Turn 0
   (neutral, enumerate) proposed 5 factors; Python assigned `RF00`-`RF04`
   regardless of whatever placeholder the model sent for `factor_id`. Every
   subsequent scoring turn correctly referenced those Python-assigned ids
   (`RF00` through `RF04`), and the adjudication turn (turn 3) correctly
   scored only the one id (`RF03`) the ledger's `severity_spread`/
   `likelihood_spread` computed as contested — the contested-only routing
   worked exactly as designed on the first live attempt.

4. **The risk panel produces real disagreement, unlike the debate's near-
   total entrenchment (Phase 5 item 4).** On the one live run: aggressive
   scored RF00-RF04 as low-severity/low-likelihood ("moderate-likelihood,
   low-severity risks... do not invalidate ownership"), conservative scored
   the same five factors 1-2 points higher on both axes across the board
   ("elevated-likelihood, moderate-severity risks"). That is the persona
   framing (§3's `AGGRESSIVE_STANCE`/`CONSERVATIVE_STANCE`) working as
   intended — a single data point, not a measured rate, but notable given
   Phase 5 measured 29 `hold` / 1 `sharpen` / 0 `concede` across 30 debate
   turns with the same underlying model.

5. **`unquoted_evidence` fired once, on `RF04`.** RF04's `evidence_quote`
   ("Price remaining above moving averages does not guarantee sustained
   upside when momentum is failing") is the model's own synthesis of two
   `derive_relations` facts, not a verbatim span from either report — a
   plausible true positive on inspection, same shape as Phase 5's
   fundamentals-quote failures (item 6): the model paraphrases instead of
   quoting when the "quote" is really a conclusion drawn from two separate
   facts.

6. **Nothing downstream re-verifies synthesis output**, same residual Phase
   5 recorded for the debate (item 12) — `citation_verifier`/`memo_verifier`
   over the rendered memo is explicitly Phase 7 (Phase 6 plan §11), not
   attempted here. The reference-resolution and numeric guards in
   `synthesis_port.py` are the only checks between a fabricated memo claim
   and the reader.

7. **`suggested_strategy` renamed to `watch_items`** (Phase 6 plan §8.4,
   option 1) — the field most likely to drift into actionable trade advice
   is now named for what it actually held in spirit (observables that would
   change the read), not a name that invites the thing the architecture
   excludes.

## Phase 6 gap closure — determinism/stability, Research Manager + Risk Judge (logged 2026-08-25)

The Phase 6 build above was against a different exit-criteria document than
the project's actual spec, discovered after the fact. The real spec calls
for **Aggressive/Neutral/Conservative risk agents over ~3 rounds**, a
**Research Manager (Sonnet)** synthesizing the bull/bear debate and a
**Risk Judge (Sonnet)** synthesizing the risk debate and issuing the final
verdict, and two exit criteria: replaying the same debate transcript at
temperature 0 twice must produce an identical risk verdict (determinism),
and 3 samples at production temperature must agree on verdict direction
(stability). None of that was built or tested in the section above. This
section is the closure.

**Changes:**
- `RISK_MAX_ROUNDS`: 2 → 3 (`RISK_MAX_TURNS`: 6 → 9). `risk_port.turn_phase`
  generalized from a hardcoded 6-turn lookup table to a round-aware formula
  (`turn_index % 3`), so a 3rd round is a second adjudicate/respond cycle
  over the ledger's still-contested set, not a new phase.
- The single unified `synthesis_port.run_synthesis` (one Sonnet-or-whatever
  call producing bull_case/bear_case/risk_narrative/verdict together) is
  replaced by two sequential calls: `run_research_manager` (sees the debate
  only, never the risk ledger, produces a `preliminary_verdict`) and
  `run_risk_judge` (sees the ledger AND the Research Manager's own output,
  issues the FINAL `verdict` — empowered to override). `DecisionMemo`
  gained `research_thesis`/`research_preliminary_verdict` so an override is
  visible in the memo itself, not folded invisibly into one paragraph —
  `decision_memo_port.py` now prints "OVERRIDDEN by the Risk Judge" or
  "affirmed" right under the verdict line.
- `RESEARCH_MANAGER_MODEL`/`RISK_JUDGE_MODEL` follow the project-wide
  `LLM_CLAUDE_MODEL` (Haiku 4.5), same as every other port in this
  pipeline — NOT pinned to Sonnet, despite the spec text naming it. First
  built pinned to `claude-sonnet-5`, then switched back after item 1 below
  was found: Sonnet 5's `temperature` deprecation undercuts exactly the
  determinism guarantee these two calls exist to support. Item 2's table is
  the re-verified Haiku run.

1. **[Found live, fixed] `claude-sonnet-5` has DEPRECATED the `temperature`
   parameter — it 400s ("temperature is deprecated for this model"), not
   merely ignores it.** Discovered running the determinism check itself:
   Haiku 4.5 (this project's `RISK_MODEL`) accepted `temperature=0` on the
   identical call shape; Sonnet 5 rejected it outright on the very first
   Research Manager call. `debate_port.create_with_temperature_fallback`
   now wraps every port's `messages.create` call: on that specific error it
   retries once without `temperature`, logging loudly that it did — a
   silently-dropped `temperature=0` on a determinism check would make the
   check pass by accident rather than by the guarantee it claims to test.
   Not hardcoded to a model list (which goes stale the moment a new model
   ships); reacts to the API's own stated capability instead.

   **Consequence for the determinism criterion, stated plainly:** because
   Sonnet 5 has no temperature lever, the "temperature=0" and "production
   temperature" trials run the Research Manager/Risk Judge at the SAME
   fixed default in both — they are not two genuinely different conditions
   for those two calls the way they are for the (Haiku) risk-panel turns,
   which DID honor `temperature=0` for real. What was actually verified is
   narrower than the criterion's literal wording: 5 independent replays of
   one fixed debate transcript through the full risk-panel + Research
   Manager + Risk Judge pipeline, at every setting currently available to
   Sonnet 5, produced the same verdict every time — a real empirical
   stability result, just not a temperature-controlled one for the two
   roles the spec cares about most.

2. **Measured (MSFT, `--as-of 2026-08-24`, one fixed 6-turn debate, 5
   pipeline replays via `scripts/risk_determinism_check.py`), first on
   Sonnet, then re-run after the Haiku switch-back:**

   **Sonnet run** (Research Manager/Risk Judge fell back off `temperature`
   per item 1 — degraded condition, both trial types at the same fixed
   default for those two calls):

   | trial | risk-panel temp | verdict | research lean | overridden | ledger | contested | confidence |
   |---|---|---|---|---|---|---|---|
   | determinism-1 | 0.0 | hold | hold | no | 6 | 0 | 0.56 |
   | determinism-2 | 0.0 | hold | hold | no | 6 | 1 | 0.51 |
   | stability-1 | production | hold | hold | no | 5 | 2 | 0.44 |
   | stability-2 | production | hold | hold | no | 5 | 3 | 0.36 |
   | stability-3 | production | hold | hold | no | 5 | 1 | 0.49 |

   **Haiku run** (`temperature` genuinely honored end to end — the
   determinism trials are now a real controlled condition for the Research
   Manager and Risk Judge too, not just the risk panel):

   | trial | risk-panel temp | verdict | research lean | overridden | ledger | contested | confidence |
   |---|---|---|---|---|---|---|---|
   | determinism-1 | 0.0 | hold | hold | no | 5 | 3 | 0.42 |
   | determinism-2 | 0.0 | hold | hold | no | 5 | 4 | 0.36 |
   | stability-1 | production | hold | hold | no | 6 | 2 | 0.47 |
   | stability-2 | production | hold | hold | no | 5 | 2 | 0.45 |
   | stability-3 | production | hold | hold | no | 5 | 4 | 0.36 |

   **DETERMINISM: PASS on both runs. STABILITY: PASS on both runs** — 10/10
   `hold` across both models, direction unanimous. The Risk Judge never
   overrode the Research Manager on any trial in either run; ledger size
   and contested-factor count varied turn-to-turn (5-6 factors, 0-4
   contested) even though the verdict did not — the risk PANEL's own
   content is not claimed deterministic, only the final verdict it feeds
   into.

   Cost: **$0.83** for the Sonnet run, **$0.63** for the Haiku re-run
   (Haiku's lower per-token rate, not fewer calls) — one-off verification
   costs, not a per-run production cost.

3. **One ticker, not a statistical guarantee**, same caveat Phase 5's own
   five-run debate sweep carried and said explicitly (Phase 5 section,
   opening note): 10/10 agreement across two model configurations on the
   SAME fixed debate transcript is reassuring but is not ten independent
   data points — the debate itself was never varied, so this cannot rule
   out that MSFT's transcript here simply argues clearly enough that no
   reasonable risk read moves the verdict. Re-running this against a second
   ticker, and especially against an input where the risk panel itself
   lands closer to a genuine 50/50 split, would be the next check worth
   running before treating "PASS" here as more than it is.

## Phase 6 determinism correction (logged 2026-08-25, same day, external code review)

Everything above this section stood for a few hours before an external
review of the checklist found two things the "PASS" verdicts had not
actually ruled out. Not removing the section above — it's what was
believed and why, at the time — this is the correction, per this file's
own rule of recording what changed rather than editing history away.

1. **[Found by review, confirmed and fixed] `build_risk_ledger` silently
   discarded every score revision from round 2 onward.** The guard `if
   turn.persona in entry.scores: continue` was checked against `entry.scores`
   — state that persists across the WHOLE turn loop — not against
   turn-local state. Intended to catch one turn emitting two scores for the
   same factor (a model error), it also caught the thing that was never
   supposed to be caught: a persona's turn-4 "respond" revision of its own
   turn-1 score, or neutral's turn-6 re-adjudication of its own turn-3
   verdict. Both look identical to the guard — "this persona already has a
   score for this factor" — so both were dropped. The risk panel's turns
   argued, revised, and re-adjudicated for real; `build_risk_ledger` kept
   only round 1's numbers, permanently, for the entire life of this
   feature. `contested` and `confidence` were therefore computed from
   frozen first-round positions, not from wherever the personas actually
   landed after seeing each other's reasoning — which is the entire
   justification for having more than one round.

   Fixed by scoping the duplicate-detection to the current turn only
   (`scored_this_turn`, reset every turn) while letting a later turn
   overwrite `entry.scores[persona]` unconditionally. Verified as a real
   regression, not a hypothesis: two new tests in `test_risk_ledger.py`
   were run against the pre-fix code first (both failed, reproducing the
   exact stale-score values) and again after (both pass).

2. **[Found by review, confirmed by re-running with a wider observable]
   The determinism claim from item 2 above does not survive checking
   anything besides the verdict.** `scripts/risk_determinism_check.py` now
   compares four observables between the two `temperature=0` replays —
   verdict, the full per-`factor_id` ledger scores, the contested set, and
   the resolved reference set actually cited in the memo — instead of only
   the verdict. Re-run (MSFT, `--as-of 2026-08-24`, Haiku, with the ledger
   fix from item 1 in place):

   ```
   verdict:        MATCH   (hold / hold)
   ledger_scores:  MISMATCH  — RF03: [severity 3,3] -> [severity 4,4]
                     (both personas shifted by the same +1, likelihoods
                     unchanged, between the two temperature=0 replays)
   contested_set:  MATCH   (both empty)
   resolved_refs:  MISMATCH — one extra debate claim cited in replay 2
   ```

   **Determinism: FAIL on 2 of 4 observables**, even with `temperature=0`
   genuinely sent and accepted (no fallback fired). The verdict-only
   criterion, as literally worded, still passes — `hold` both times — but
   that is now known to be true DESPITE the underlying process not being
   deterministic, not BECAUSE it is. Most likely explanation: `temperature=0`
   makes next-token sampling greedy but does not guarantee bit-identical
   output across calls on Anthropic's serving stack, which is a documented
   property of production LLM inference generally (batch composition,
   floating-point non-associativity), not something this project's
   temperature plumbing got wrong. Nine sequential risk turns plus two
   synthesis calls gives that variance nine-plus opportunities to
   compound; this run, it surfaced in one factor's score and one citation,
   not in the verdict. A different run could surface it in the verdict
   instead — nothing here rules that out.

   Stability's widened metrics tell the same story from the production-
   temperature side: across the 3 samples, verdict direction held (`hold`
   x3) but the contested-set Jaccard similarity was **0.00** — no two of
   the three samples agreed on which factor was contested — and confidence
   spread was 0.12 (0.60/0.48/0.60). The verdict is stable; the risk read
   underneath it is not, and the stability criterion as specified has no
   way to see that.

3. **Net effect on the exit-criteria table**: criterion 4 (determinism) as
   LITERALLY worded — replay twice at temperature 0, verdict identical —
   still passes on every run to date. Criterion 4 as a claim about the
   PIPELINE being deterministic does not, and should not be represented as
   closed. Criterion 5 (stability) is unchanged in its literal pass, but
   its power to detect a real problem remains close to zero given finding
   4 in the section above (every verdict this project has ever produced,
   29 of 29 counting this run, is `hold`) — a stability check that cannot
   distinguish "the pipeline is stable" from "the pipeline always says
   hold" is not exercising the property the criterion is meant to protect.

   The fabrication-laundering, `reasoning`/`verdict`-coherence, and
   `recursion_limit`-superstep concerns raised in the same review were
   checked directly against the current code and do NOT apply: the Risk
   Judge's numeric-guard corpus never includes the Research Manager's own
   prose (`_numeric_corpus` in `synthesis_port.py` — reports, debate
   claims, ledger text, risk-score rationales only); `reasoning` and
   `verdict` are both set from the same `RiskJudgePayload` in
   `run_synthesis`, so they cannot originate from different agents; and
   Research Manager + Risk Judge run sequentially inside the single
   `synthesizer` graph node, not as two graph nodes, so they cost zero
   additional LangGraph supersteps — `RECURSION_LIMIT` (27, derived live
   from `RISK_MAX_ROUNDS`, not a literal) already accounts for this
   correctly.

**Next check worth running, if this is picked back up**: a ticker/date
combination with a genuinely bearish or genuinely contested setup, to
establish whether the pipeline can produce a non-`hold` verdict at all —
without that, "stability" is unfalsifiable by construction. Second
priority: repeat the widened 4-observable determinism check on that input,
since the one non-degenerate result available so far (this section) is a
single ticker, single fixed debate transcript, and already failed 2 of 4
observables.

## Phase 6 determinism/stability, resolved on a contested ticker (logged 2026-08-26)

The "next check" from the section above: ran the same widened check against
AVGO (`--as-of 2026-08-25`, fresh fixed 6-turn debate, real API calls
throughout, Haiku). This is no longer a degenerate distribution — the
debate leaned bearish and the risk panel produced a real, contested read.

**Determinism (temperature=0, replayed twice):**

```
verdict:        MATCH    (sell / sell)
ledger_scores:  MISMATCH
contested_set:  MISMATCH  (trial 1: {RF03, RF04}; trial 2: {RF00, RF03})
resolved_refs:  MATCH
DETERMINISM: FAIL (2/4 observables matched)
```

**Stability (production temperature, 3 samples) — FAILS outright, not a
near miss:**

| sample | research lean | verdict | overridden |
|---|---|---|---|
| stability-1 | sell | **sell** | no |
| stability-2 | sell | **hold** | **yes — caught live** |
| stability-3 | hold | **hold** | no |

`['sell', 'hold', 'hold']` — verdict direction does not agree across the
three samples. Sample 2 is the first live instance in this project's
history of the Risk Judge actually exercising its override power: the
Research Manager leaned `sell` from the debate, the Risk Judge reviewed the
risk panel and overrode to `hold`. That mechanism was built and tested with
mocks (`test_synthesis_port.py`) but never observed on a real run until
this one — confirms the override path works, and simultaneously is the
reason stability fails: whether the Judge overrides or not turned out to
depend on run-to-run variance, not on some judgement holding steady sample
to sample.

Confidence spread 0.07 (0.59/0.56/0.52) — narrow, notably tighter than the
verdict disagreement would suggest. Contested-set Jaccard 0.00 again — as
on MSFT, no two samples agreed on which factor was contested.

**Conclusion: criteria 4 and 5, tested on an input where they can actually
say something, both fail.** MSFT's result (Phase 6 determinism correction,
above) was consistent with "the pipeline is stable" and with "the pipeline
always says hold" and could not distinguish them. AVGO removes that
ambiguity: given a debate that leans bearish, the final verdict is NOT
stable across production-temperature samples, and even at temperature=0 the
ledger's substance (which factors end up contested, what score each
persona lands on) is not reproducible either. The literal wording of
criterion 4 (verdict identical across two temp=0 replays) still passes here
by coincidence — both replays happened to land on `sell` — but criterion 5
(verdict direction across 3 production samples) does not, on the same
run, with the same code.

Cost: $0.57 for this run (one debate + 2 determinism trials + 3 stability
trials, Haiku throughout). One `KeyError` in the reporting script itself
(mismatched key name between the `checks` display list and the per-trial
detail dict) was found and fixed mid-investigation — see the commit fixing
`scripts/risk_determinism_check.py`; it took down the first AVGO attempt
right after determinism reported a real mismatch, before the stability
section ran, and had to be re-run.

**Status: Phase 6's determinism/stability exit criteria are NOT met.** Not
"met with a caveat" — failed, on the one input tested so far that isn't
degenerate. What would need to change to close this honestly: either the
criteria get redefined around what temperature=0 can actually guarantee on
production LLM serving (verdict-level stability under some tolerance,
rather than bit-identical ledger reproduction), or the Risk Judge's
decision process needs something that isn't pure sampling variance
deciding a sell/hold override — e.g. a majority-of-N-samples rule, or
constraining what "contested" can mean turn to turn. Neither is attempted
here; this section's job is to say plainly that the gap is real; deciding
how to close it is a design call this file has been recording, not making.

## Phase 6 determinism, localized (logged 2026-08-26, external review directed)

The AVGO section above established that determinism and stability fail; it
did not establish WHERE the variance enters. A second review pass asked for
that directly, in order of cost: does the RENDERED PROMPT differ between
replays (a bug this project owns), does the "replay" actually hold upstream
state fixed, or is it the model. Answered by measurement, not inference —
`scripts/localize_risk_variance.py`, new this section.

**Category 1 (mine, in Python) — CLEAR, measured at zero API cost.**
`build_risk_evidence_pack` called twice on the identical fixed state
produces byte-identical output (14,237 chars, checked both before and after
the correction below). Grepped the risk/synthesis ports for raw `set`
iteration rendered into prompt text: every one found is either post-
processing (never rendered) or passed through `sorted()` first. Also
already weakly true by construction: both temperature=0 trials run in one
Python process, so even an unsorted-set bug would iterate identically for
both (`PYTHONHASHSEED` doesn't vary within one process) — checked directly
anyway rather than resting on that alone.

**Category 2 (mine, upstream) — CLEAR, confirmed by identity, not
inspection.** `technical_report` and `debate_turns` are the same object
(`is`, not `==`) across a trial-shaped shallow copy of the fixed state. No
RAG retrieval runs in this script at all (technical-only) — Phase 2's
documented retrieval non-determinism cannot be the cause here by
construction.

**Category 3 (the model's) — CONFIRMED, and localized to turn 0, the very
first call.** First attempt at this measurement was wrong and is worth
recording as a mistake, not quietly fixed: the initial turn-snapshot
compared only `(factor_id, text, trigger, horizon, evidence_ref)` for
proposed factors and `(factor_id, severity, likelihood)` for scores —
never `payload.argument`, never `rationale`. That snapshot reported turn 0
AND turn 1 as "byte-identical," then reported turn 2's PROMPT as a
mismatch — which would have been filed as a category-1 bug, except reading
the actual turn-1 transcript text embedded in that "mismatched" prompt
showed the two replays' turn-1 ARGUMENT and RATIONALE prose already
differed in wording (structured severity/likelihood numbers matched;
free text didn't) — the divergence was real at turn 1, the snapshot
just wasn't looking at the field it was in. Fixed the snapshot to include
every text field and re-ran: **turn 0 itself, the very first call, already
differs** — different argument prose, and the two replays proposed
factors covering different content (e.g. replay A's RF00 was MACD/
momentum-based, replay B's RF00 was a Bollinger Band breach) — from a
byte-identical prompt, at temperature=0.

**Net: category 3, and it's not something that accumulates over a long
panel — it's present at the first token generated.** This is conclusive
given categories 1 and 2 are independently clear: `temperature=0` gives
greedy decoding, not bitwise reproducibility, on this model's serving
stack, confirmed rather than assumed from provider documentation.

**Criterion 3, amended per the same review:** "the override mechanism
executes correctly when it fires" is the supportable claim, observed once
(AVGO stability-2). "The override fires when it should" has no evidence
either way yet — recorded separately so the two don't collapse into one
claim in a future summary.

**Criterion 2, corrected:** "ledger entries carry scores from all three
personas" is a proxy that a single full round also satisfies. The direct
check — `len(risk_turns) == 9` and `max(round_num) == 3` — is now asserted
in `run_pipeline_once` itself (structural, since `round_num` is
Python-assigned from `turn_index`, never model output; a future change to
the turn-count loop now fails loudly here rather than passing on a proxy).

**Restated criterion 4, wired in but not yet re-measured on a fresh run:**
`_report_aggregate_determinism` now reports, alongside the strict
per-observable check, whether the ledger's AGGREGATE statistics (contested
count, total severity mass, total likelihood mass) match across the two
temperature=0 replays — the quantity a computed-from-aggregates verdict
would actually depend on, as opposed to per-factor identity. On the one
AVGO run measured before this function existed (computed by hand from the
saved JSON): contested count held (2/2), severity mass held (51/51),
likelihood mass held (31/31) — only contested-factor MEMBERSHIP moved
(RF04 swapped for RF00). That is the favorable outcome for a
compute-the-verdict-from-aggregates design.

**But that measurement now needs a caveat the turn-0 finding forces**: if
individual factor enumeration and argument prose already differ this much
at the very first call, a 9-turn panel's aggregate stability — if it holds
on a re-run — is something the THREE-ROUND ADJUDICATION PROCESS achieves
despite substantial early variance, not evidence that variance is small to
begin with. Worth re-measuring with `_report_aggregate_determinism` now
that it exists, before trusting the one hand-computed data point.

**Also unresolved**: whether AVGO's split (a clearly one-directional
technical picture, MACD/price/RSI all pointing the same way) is a case a
panel should have converged on and didn't, or whether every ticker shows
this much panel noise regardless of how one-sided the underlying evidence
is. That distinction decides whether the fix belongs in the scoring prompts
(panel noise, general) or in a boundary-case abstention design (this input
specifically was marginal). Not decided here — the next measurement is
running this same localization against a ticker with an UNAMBIGUOUS
technical picture (not just directionally clear like AVGO, but extreme) and
checking whether turn-0 variance shrinks.
