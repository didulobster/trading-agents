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

16. **[Cross-phase, CONFIRMED live] `technical_node` derives `as_of_date`
    from `df.index[-1]` and ignores `state["as_of_date"]`** (Phase 4 gap 6).
    The debate is the first node to read all four reports side by side, so it
    is the first place a mixed-vintage evidence pack can produce a
    confidently wrong argument.

    *Observed (AVGO, 2026-08-23):* the run was invoked `--as-of 2026-08-20`
    and the technical report came back `as_of=2026-08-21`. Six debate turns
    then argued in detail over a last close and a set of moving averages
    from **the day after the run's stated bound**, and the memo is dated
    2026-08-20. Nothing in the memo says the price evidence is from a later
    date. Not a Phase 5 bug, but Phase 5 is where it stopped being
    theoretical: the debate spent its entire transcript on a 0.15-point
    margin that belongs to a bar the run was not supposed to see.
