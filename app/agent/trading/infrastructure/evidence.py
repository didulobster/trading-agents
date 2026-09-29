"""The evidence pack, and the grounding checks run against it.

The pack is the analyst reports a debater, risk persona or judge is shown and
may cite. Each grounding check answers one question about model output: does
this figure, quote or stated direction have support in the pack? They flag;
the caller decides whether a flag records or rejects.
"""

from __future__ import annotations

import re

from app.agent.trading.application.technical_indicators import derive_relations
from app.agent.trading.domain.news_digest import AGGREGATED_RELEVANCE
from app.agent.trading.domain.trading_state import ANALYST_OUTPUTS


# ---------------------------------------------------------------------------
# Evidence pack
# ---------------------------------------------------------------------------

def _not_run(name: str) -> str:
    """A missing analyst leg is stated, not omitted.

    `--only news` leaves fundamentals_report and technical_report as None. If
    the pack simply had no fundamentals section, a debater would read the
    silence as neutrality — the exact error the news caveats exist to prevent
    one layer up.
    """
    return (
        f"{name.upper()}: NOT RUN — no {name} evidence is available for this "
        f"debate. Do not infer anything about {name} from its absence."
    )


def _render_technical(report, *, quotable: bool = False) -> str:
    """Relations FIRST, then the raw values, then the prose.

    The relations block is Phase 3's `derive_relations` — the comparisons
    computed in Python precisely because a model asked to work them out from
    raw numbers gets them wrong. The pack used to hand the debaters the JSON
    and nothing else, throwing that away, and on the first live Haiku turns
    BOTH sides called an RSI of 38.7 "oversold". It is not, and the relations
    block says so in as many words. Every number in those turns was real, so
    the numeric guard had nothing to catch — the same shape as the MSFT
    moving-average error that made `derive_relations` exist.

    It also gives the debaters something QUOTABLE. `evidence_quote` is a
    single contiguous span, and a trend claim rests on two values that sit
    far apart in the JSON, so an honest citation of both was a splice and got
    flagged. One relation line carries both values and the comparison
    between them.

    The JSON stays — in the pack the number-fabrication guard scans. It is
    the only source of full precision, and a claim in prose that turns on the
    fourth decimal has nowhere else to cite.

    `quotable=True` drops the JSON line. Containment on a serialized dict
    lets `evidence_quote` cite `macd_histogram":0.3556307403914323` verbatim
    — the check passes, because it IS in the pack, but the debater is
    grepping the raw blob rather than citing anything the analyst actually
    said. Found live (ACN, technical-only pack, 2026-08-24): 2 of 4 claims in
    one turn quoted a raw JSON key:value fragment this way. Used only for the
    quote-check corpus (`quotable_texts`) — `build_evidence_pack` still gets
    the full render, so the number-fabrication guard keeps the precision
    backstop and a faithfully-copied figure in argument prose is not falsely
    flagged as fabricated.
    """
    relations = "\n".join(f"- {r}" for r in derive_relations(report.indicators))
    header = (
        f"TECHNICAL (as of {report.as_of_date}, {report.data_source}, "
        f"{report.bars_used} bars):\n"
        f"Computed relations (AUTHORITATIVE — worked out in code, not by a "
        f"model. State them as given; never contradict them, and never "
        f"re-derive a comparison yourself from the raw values below):\n"
        f"{relations}\n"
    )
    if not quotable:
        header += f"Indicators (full precision): {report.indicators.model_dump_json()}\n"
    return header + f"Interpretation: {report.interpretation}"


def _render_news(digest) -> str:
    """Only the articles the sentiment aggregate counts, and a line saying so.

    The pack used to carry every item the vendor returned. On AVGO that was
    188 articles of which 127 were `mentioned` or `unrelated` — coverage the
    sentiment node had ALREADY judged not primarily about the company — and
    they consumed 39% of the whole evidence pack. The debate cited news once
    in 25 claims, so that was context nobody read, paid for on every turn.

    Filtered on AGGREGATED_RELEVANCE rather than a literal, so the pack and
    the sentiment aggregate cannot disagree about what counts as evidence
    about this company. One constant, one policy.

    The omission is STATED, not silent. A debater shown 61 articles with no
    further comment reads that as the whole feed, and the pack's own rule —
    the same one behind the NOT RUN blocks — is that absence must be visible.
    """
    shown = [i for i in digest.items if i.relevance in AGGREGATED_RELEVANCE]
    hidden = len(digest.items) - len(shown)

    header = (
        f"NEWS ({digest.window_start} to {digest.as_of_date}, "
        f"{len(shown)} of {digest.raw_article_count} vendor article(s) shown, "
        f"truncated_by_cap={digest.truncated_by_cap}):"
    )
    notes = []
    if hidden:
        notes.append(
            f"{hidden} further article(s) in the feed mentioned the company or "
            f"were unrelated to it and are NOT listed. Their absence is a "
            f"filtering decision, not evidence of quiet news flow."
        )
    if not shown:
        notes.append(
            "NO article in the window was primarily about this company. That is "
            "an ABSENCE of news evidence, not neutral news — do not argue from "
            "it in either direction."
        )

    lines = [header, *notes]
    for item in shown:
        lines.append(
            f"- [{item.published_date}] ({item.relevance}/{item.sentiment}) "
            f"{item.headline}: {item.summary}"
        )
    return "\n".join(lines)


def _render_sentiment(summary) -> str:
    return (
        f"SENTIMENT (as of {summary.as_of_date}): net_score {summary.net_score:+.3f} "
        f"over {summary.article_count} article(s) primarily about the company "
        f"(+{summary.positive} / -{summary.negative} / ={summary.neutral}); "
        f"{summary.excluded_by_relevance} excluded as not primarily about it. "
        f"An article_count of 0 is an absence of evidence, not neutral evidence."
    )


def report_texts(state) -> dict[str, str]:
    """One text block per `evidence_ref` value, keyed by that value.

    Also the corpus the quote check runs against, which is why it is built
    once and reused rather than re-rendered per claim.
    """
    fundamentals = state.get("fundamentals_report")
    technical = state.get("technical_report")
    digest = state.get("news_digest")
    sentiment = state.get("sentiment_summary")
    return {
        "fundamentals": (
            f"FUNDAMENTALS:\n{fundamentals.summary}"
            if fundamentals is not None
            else _not_run("fundamentals")
        ),
        "technical": (
            _render_technical(technical)
            if technical is not None
            else _not_run("technical")
        ),
        "news": _render_news(digest) if digest is not None else _not_run("news"),
        "sentiment": (
            _render_sentiment(sentiment)
            if sentiment is not None
            else _not_run("sentiment")
        ),
    }


def quotable_texts(state) -> dict[str, str]:
    """`report_texts`, but for the corpus `check_quotes` validates against.

    Identical for every source except technical, where the raw indicators
    JSON is dropped — see `_render_technical`'s `quotable` docstring for why.
    `build_evidence_pack` keeps calling `report_texts` (unchanged), so the
    number-fabrication guard still has the JSON as ground truth; only the
    quote check loses it.
    """
    texts = report_texts(state)
    technical = state.get("technical_report")
    if technical is not None:
        texts["technical"] = _render_technical(technical, quotable=True)
    return texts


def build_evidence_pack(state) -> str:
    """Built off ANALYST_OUTPUTS order so a partial run produces the same
    section order as a full one — a pack whose layout changes with the run
    shape is a pack whose cache never hits."""
    texts = report_texts(state)
    order = list(ANALYST_OUTPUTS) + ["sentiment"]
    return (
        f"EVIDENCE PACK — {state['ticker'].upper()}\n\n"
        + "\n\n".join(texts[name] for name in order)
    )


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

# A number with an optional sign, where '-' is read as a sign only if the
# preceding character can't make it a separator instead: a digit or '.' means
# a numeric range ("318.73-352.11"), a '%' means a percentage range
# ("88%-89%"). Both are ordinary phrasings, and reading their hyphen as a
# minus turns the second endpoint into a negative number that matches no
# indicator value.
_SIGNED_NUMBER = r"(?<![\d.%])-?\d+\.?\d*"

# Window labels, stripped before the value-check because they name a period
# rather than report a measurement. Two spellings, both seen live:
#
#   "the 200-day average"            -> the plain compound
#   "the 50- and 200-day averages"   -> a suspended hyphen, where the noun is
#                                       carried by the second term only
#
# The second cost a false positive: "200-day" was stripped, the dangling "50-"
# was not, and the orphaned 50 matched no indicator value. The lookahead is
# restricted to a following conjunction so this only ever fires on a genuine
# suspended compound — matching any digit-hyphen-space would eat the first
# endpoint of a spaced range like "318.73 - 352.11".
_PERIOD_LABEL = re.compile(r"\b\d+-day\b|\b\d+-(?=\s+(?:and|or|to)\s)")


def unmatched_by_tolerance(text: str, known_values: list[float]) -> list[str]:
    """Cheap guard, not a full verifier: extract numbers mentioned in the interpretation
    and check each is within rounding tolerance of some value actually in `indicators`.
    Flags (doesn't block) anything that doesn't match — surfaced in TechnicalReport for
    human review, same spirit as the 'Unverified Figures' section in memo_verifier.

    Still a review signal rather than an auto-reject: it can produce false positives on
    narrative numbers that reference thresholds rather than indicator values themselves.
    The RSI band edges were the recurring instance of that and are now exempted near
    RSI context (see _is_rsi_band_reference) — they were unmatchable by construction,
    and the derived-relations block made the model restate them on every run, so the
    guard was reporting the same two numbers forever. Other threshold vocabulary
    (Bollinger deviations, MACD zero-line talk) has not shown up in practice and is
    left alone rather than pre-emptively exempted.

    Three known transformations are normalized before flagging, each patched from a
    real false positive rather than designed upfront — coverage is only as good as
    the phrasing actually tested, not something derivable from first principles:

    1. Period-descriptor phrases ("50-day", "200-day") are stripped before scanning,
       since those are label numbers (the SMA/RSI window length), not data values. This
       narrows the false-positive surface but opens a corresponding gap: a fabricated
       period ("the 55-day average") would slip through unflagged, since it's stripped
       before the value-check ever sees it. See
       test_flag_unmatched_numbers_does_not_catch_fabricated_period_label for that
       documented boundary.
    2. "N%" mentions are checked against known_values/100 as well as known_values
       directly — confirmed necessary when volume_vs_20d_avg=0.529 was faithfully
       reported as "53%" and would otherwise have been flagged as fabricated.
    3. "N% above/below" mentions are checked against (known_value - 1) * 100 —
       a distinct transform from #2: "22% above the 20-day average" describes a
       *delta* from a ratio-type value (volume_vs_20d_avg=1.2153 -> (1.2153-1)*100
       = 21.5% =~ "around 22"), not the raw ratio-as-percentage. Matched (and
       consumed) before the general percent pattern so the two don't collide.
       Both endpoints of a range ("21%-22% above the 20-day average") are
       captured by the one match, because only the endpoint touching the
       keyword carries the "above/below" context — matching it alone leaves
       the other orphaned for the general percent rule, which then tests a
       delta as though it were a ratio and flags faithful text.

    A leading '-' counts as a sign only where it can't be a range separator
    (_SIGNED_NUMBER). Negative indicator values are ordinary — a bearish
    macd_histogram of -1.2158 gets reported as "around -1.22" — so the sign
    has to parse, but reading every hyphen as one turned a faithful
    "318.73-352.11" band into a fabricated "-352.11" and flagged a real
    bb_upper value. This is a parsing fix, not a tolerance one: unlike the
    threshold false positives above ("RSI above 70"), the number was a
    genuine indicator value that the scanner mangled before comparing it.
    """
    # Normalize U+2212 MINUS SIGN to ASCII before anything reads a sign. The
    # model writes typographic minus roughly one run in four — "negative
    # histogram of −3.23" — and _SIGNED_NUMBER only knows the ASCII hyphen, so
    # a faithful -3.2298 parsed as positive 3.23 and matched nothing. Python
    # agrees on the narrower alphabet: float("−3.23") raises.
    #
    # Only U+2212, not the dashes. En dash is the conventional range separator
    # ("318.73–352.11"), and the whole reason _SIGNED_NUMBER carries a
    # lookbehind is that reading a separator as a sign turned a real Bollinger
    # band into a fabricated negative.
    text = text.replace("−", "-")
    text_no_periods = _PERIOD_LABEL.sub("", text)

    flagged: list[str] = []

    above_below_pattern = re.compile(
        rf"({_SIGNED_NUMBER})%(?:\s*-\s*({_SIGNED_NUMBER})%)?\s*(?:above|below)"
    )
    for endpoints in above_below_pattern.findall(text_no_periods):
        for m in (e for e in endpoints if e):
            delta_pct = float(m)
            if not any(abs(delta_pct - (kv - 1) * 100) <= max(1.0, abs(kv) * 2) for kv in known_values):
                flagged.append(f"{m}% above/below")
    text_no_above_below = above_below_pattern.sub("", text_no_periods)

    percent_pattern = re.compile(rf"({_SIGNED_NUMBER})%")
    for m in percent_pattern.findall(text_no_above_below):
        ratio = float(m) / 100
        if not any(abs(ratio - kv) <= max(0.01, abs(kv) * 0.02) for kv in known_values):
            flagged.append(f"{m}%")
    text_no_percents = percent_pattern.sub("", text_no_above_below)

    for match in re.finditer(_SIGNED_NUMBER, text_no_percents):
        m = match.group()
        val = float(m)
        if any(abs(val - kv) <= max(0.5, abs(kv) * 0.02) for kv in known_values):
            continue
        if _is_rsi_band_reference(val, text_no_percents, match.start(), match.end()):
            continue
        flagged.append(m)

    return flagged


# The conventional RSI band edges. These are constants of the indicator, not
# values read off it, so they can never appear in `indicators` and were
# guaranteed to flag — "RSI above 70" was documented as a known false positive
# from the start, and adding a relations block that says "NEITHER overbought
# nor oversold (between 30 and 70)" made the model echo them every run.
#
# Only 30 and 70. The 20/80 variant exists, but every value added here is a
# value the guard can no longer catch anywhere it appears, and 20 and 80 are
# far likelier to collide with a genuine price or indicator reading.
_RSI_BAND_VALUES = {30.0, 70.0}

# Required nearby for the exemption to apply, so 30 and 70 stay checkable
# everywhere else — a fabricated "P/E ratio of 30" is still flagged.
_RSI_CONTEXT = re.compile(r"\brsi\b|overbought|oversold", re.I)

# Asymmetric because the giveaway usually precedes the number ("RSI ...
# between 30 and 70") and only sometimes follows it ("70, neither overbought
# nor oversold"). Wide enough to reach back past "sits comfortably in neutral
# territory between 30 and", narrow enough not to borrow an RSI mention from
# a neighbouring sentence.
_RSI_LOOKBEHIND = 90
_RSI_LOOKAHEAD = 60


def _is_rsi_band_reference(value: float, text: str, start: int, end: int) -> bool:
    """True when a number is one of the RSI band edges, used as a threshold.

    Scoped by proximity rather than exempted outright: this narrows the
    guard's blind spot to "30 or 70 written within a sentence's reach of the
    word RSI", instead of blinding it to those two values everywhere.
    """
    if value not in _RSI_BAND_VALUES:
        return False
    window = text[max(0, start - _RSI_LOOKBEHIND) : end + _RSI_LOOKAHEAD]
    return _RSI_CONTEXT.search(window) is not None


# Comma-aware, and a '-' counts as a sign only where it cannot be something
# else. Two lookbehinds, each patched from a real false positive rather than
# designed up front:
#
#   1. A RANGE separator, the Phase 3 lesson: reading every hyphen as a minus
#      turned a faithful "318.73-352.11" band into a fabricated "-352.11".
#   2. A HYPHENATED COMPOUND, found on the first live debate (AVGO,
#      2026-08-23): "the low-30s oversold zone" and "sub-50-SMA price" were
#      read as -30 and -50 and reported as fabricated figures. Two of the six
#      flags that run, so it is not a rare shape.
#
# The second lookbehind has to cover the digit as well as the sign. Blocking
# only "<letter>-<digits>" would leave the scanner free to start one
# character later and flag a bare "30" out of "low-30s" — the same false
# positive with the sign filed off.
_DEBATE_NUMBER = re.compile(
    r"(?<![\w.%,])(?<![A-Za-z]-)(-?\d[\d,]*\.?\d*)(%?)"
)


def unbacked_figures(text: str, evidence_pack: str) -> list[str]:
    """Every figure in a debate turn must appear verbatim in the evidence pack.

    Containment rather than the Phase 3 tolerance match, and the difference
    matters. That guard works over ~10 well-separated TechnicalIndicators
    values at tolerance max(0.5, |kv|*0.02), where a fabricated number
    usually misses all of them. Scrape every number out of a fundamentals
    memo and there are a hundred-plus known values carrying the same bands;
    in dense regions those bands overlap and cover most of the number line, a
    fabricated figure lands inside somebody's band, and the guard returns []
    forever while reading as clean.

    Containment is also the semantically correct check here: the debater's
    job is to CITE the analysts' numbers, not compute new ones, so a figure
    that is not in the pack is unbacked whatever its value.

    Two faithful restatements are cleared before anything is flagged, both
    forced by live output rather than designed up front:

    1. ROUNDING, which is what prose does to figures. The first two live
       turns wrote "RSI of 41.2" for 41.2033 and "the 50-day at 330.12" for
       330.1245 — one false positive each, a 100% rate on day one, which
       would have taught the reader to skip the guard before it ever caught
       anything. Cleared by PRECISION, not tolerance: a figure clears only
       if some pack value rounds to it AT THE FIGURE'S OWN number of decimal
       places. "41.2" clears against 41.2033; "71.4" clears against nothing.
       That is far tighter than a +/-2% band and does not widen as the pack
       grows.
    2. PERCENT forms, where a faithful restatement legitimately differs from
       the source ("53%" for a volume_vs_20d_avg of 0.529, "22% above" for
       1.2153). Those are handed to the Phase 3 transforms, and only to them
       — the bare-number tolerance stage is deliberately not given veto
       power here, for the density reason above.

    3. SIGN, added 2026-08-29. The news feed says Viking "Cuts Share Stake In
       Microsoft Corp By 36.8%" and the debater wrote "Viking -36.8%" — the
       same figure, the sign carrying the direction the source states in
       words. Comparison is therefore on MAGNITUDE: "-36.8" clears against a
       pack "36.8" and vice versa.

       What that gives up, stated rather than discovered later: this guard no
       longer reports a sign INVERSION of a sourced figure — "-5.2%" written
       against a pack "+5.2%" now clears. That is the correct trade for THIS
       guard, whose question is whether a figure has a source at all, not
       whether it was read in the right direction; a magnitude present in the
       pack was not invented. Direction errors need a check that knows what
       the number means, which containment never did.

    Flags, never blocks. This guard is new enough to have unknown
    false-positive classes, and debate prose is looser than the templated
    technical interpretation, so expect more of them here than in Phase 3.
    """
    text = text.replace("−", "-")
    pack = evidence_pack.replace("−", "-").replace(",", "")

    pack_tokens = {m.group(1) for m in _DEBATE_NUMBER.finditer(pack)}
    # Magnitudes as well as signed tokens — see the SIGN note in the
    # docstring. Built from the same scan so the two can never disagree.
    pack_magnitudes = {t.lstrip("-") for t in pack_tokens}
    known: list[float] = []
    for token in pack_tokens:
        try:
            known.append(float(token))
        except ValueError:
            continue
    known_magnitudes = [abs(k) for k in known]

    # Second opinion, consulted ONLY for percent forms (see docstring).
    tolerance_flags = set(unmatched_by_tolerance(text, known))

    scanned = _PERIOD_LABEL.sub("", text)
    flagged: list[str] = []
    for match in _DEBATE_NUMBER.finditer(scanned):
        raw, percent = match.group(1), match.group(2)
        bare = raw.replace(",", "")
        if bare in pack_tokens or bare.lstrip("-") in pack_magnitudes:
            continue
        if _is_rounding_of(bare.lstrip("-"), known_magnitudes):
            continue
        if percent:
            if not ({f"{raw}%", f"{raw}% above/below"} & tolerance_flags):
                continue   # a faithful transform of a pack value
            flagged.append(f"{raw}%")
        else:
            flagged.append(raw)

    # Order-preserving dedup: the same fabricated figure repeated four times
    # is one finding, not four.
    return list(dict.fromkeys(flagged))


# Unit conversion is a power of 1000: a filing reports "$63,887" million or
# "$14,462,836k", and prose says "$63.9B". Nothing else about the figure
# changes.
_SCALE_FACTORS = (1e3, 1e6, 1e9)


def _is_rounding_of(raw: str, known: list[float]) -> bool:
    """True when some pack value rounds to `raw` at `raw`'s own precision,
    at the same scale or a power-of-1000 away from it.

    Precision-scoped on purpose. A fixed tolerance widens the guard's blind
    spot as the pack grows; this one does not — "41.2" only ever clears
    against a value in [41.15, 41.25), whatever else is in the pack.

    SCALE was added 2026-08-27 after the Phase 9 battery measured this
    guard's precision on three live memos and found it inverted: every
    "may be fabricated" figure it reported was correct and every one was a
    millions-to-billions restatement it could not see — AVGO's 63.9
    ($63,887M revenue), 35.8 ($35,819M), 5.7 ($5,747M SBC), NFLX's 10.1
    ($10,149M OCF), ACN's 69.7 ($69,673M revenue). Meanwhile the one real
    fabrication in that battery went unreported. A guard whose warnings are
    reliably wrong is worse than no guard: it teaches the reader to skip
    the category, and then the true positive arrives in a list nobody reads.

    Scale clearing is deliberately restricted to figures carrying at least
    one DECIMAL PLACE, and that restriction is the whole safety argument.
    Dividing the pack by 1000 multiplies the number of values the guard will
    clear against, which is exactly the density problem `unbacked_figures`
    exists to avoid — but only for coarse figures. A bare integer like "70"
    would clear against any pack value in [69500, 70500), a bucket 1000 wide,
    and "70" is precisely the shape of the fabricated figure this battery
    caught. A converted figure keeps its significant digits ("$63.9B", never
    "$64B") because keeping them is the point of converting; so requiring a
    decimal admits the real restatements and admits none of the round
    inventions. "63.9" still only ever clears against [63850, 63950).

    RESIDUAL, measured and accepted rather than engineered away: a
    one-decimal figure clears against a window 100 units wide at the
    1000-scale, so a coincidental match is possible in a dense corpus. Seen
    once, in the same Phase 9 re-audit: AVGO's "$2.2B" (pre-VMware SBC,
    legitimately 6.1% x $35,819M = $2,185M) cleared against an unrelated
    2,171 elsewhere in the corpus. The figure was sound and the clearance
    was luck. Tightening this by requiring an explicit magnitude unit does
    NOT help — the corpus reports in millions, so 2,171M reads as $2.17B and
    matches at the stated scale too. Containment on a rounded figure against
    a dense corpus is coarse by construction; the honest trade is 7 measured
    false positives removed against a coincidence rate that is bounded and
    documented. Precision here is what `debate_originated_numbers`
    (synthesis_port) exists to add, by asking a different question — does
    this figure have an analyst source at all — rather than a looser one.
    """
    try:
        value = float(raw.replace(",", ""))
    except ValueError:
        return False
    fraction = raw.split(".")
    places = len(fraction[1]) if len(fraction) == 2 else 0
    if any(round(kv, places) == value for kv in known):
        return True
    if places == 0:
        return False   # see the docstring: no scale clearing for bare integers
    return any(
        round(kv / factor, places) == value
        for kv in known
        for factor in _SCALE_FACTORS
    )


# ---------------------------------------------------------------------------
# Direction guard — the numbers are right and the sentence about them is not
# ---------------------------------------------------------------------------

# Only words whose direction on the CITED QUANTITY is unambiguous. "improving",
# "deteriorating", "worsening" are deliberately absent: a deteriorating ratio
# falls and a deteriorating gap rises, so they say nothing about which way the
# figures should move. Bare "up"/"down"/"higher"/"lower" are absent too — "up
# to $80 billion in debt" is not a trend claim, and it is the single most
# common shape in this feed.
_TREND_UP = frozenset({
    "widening", "widened", "rising", "rose", "risen", "growing", "grew",
    "grown", "increasing", "increased", "accelerating", "accelerated",
    "expanding", "expanded", "climbing", "climbed",
})
_TREND_DOWN = frozenset({
    "narrowing", "narrowed", "falling", "fell", "fallen", "declining",
    "declined", "shrinking", "shrank", "shrunk", "contracting", "contracted",
    "dropping", "dropped", "compressing", "compressed",
})

# FY2025 / FY 2025 / H1 2026 / Q3 FY2026 / a bare 2025. The lookahead drops
# the year out of an ISO date (2026-06-30), where the "next number" would be
# the month.
_PERIOD_TOKEN = re.compile(
    r"\b(?:(?:H[12]|Q[1-4])\s+)?(?:FY\s?)?((?:19|20)\d{2})\b(?!\s*[-/]\s*\d)"
)

# Markdown cells and line breaks end a "sentence" as surely as a full stop:
# a table row is not prose, and the words either side of a pipe are not one
# claim. Read without this, one FIG transcript joined a revenue figure from
# a metrics table to a verb from the claim row beneath it.
_SENTENCE_SPLIT = re.compile(r"(?<=[.;!?])\s+|\s*\|\s*|\n+")

# "the FY2026 10-K shows ..." must not offer 10 as FY2026's figure.
_FORM_NAME = re.compile(r"\b(?:10-[KQ]|8-K|S-1|20-F|6-K)\b", re.I)

# A figure ending the text that runs up to a period label belongs to it:
# "5.19x (FY2024)". Anchored at the end and unit-aware, because searching
# for the first number instead found "5.19" inside "5.19x", failed to match
# the text it ended with, and silently fell through to the number on the
# OTHER side of the year.
_TRAILING_VALUE = re.compile(
    r"(?<![\w.%,])-?\d[\d,]*\.?\d*\s*(?:%|x|bp|pp|[KMB]|bn|billion|million|thousand)?\s*$",
    re.I,
)

_SCALE_SUFFIX = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "t": 1e12, "trillion": 1e12,
}
# A magnitude and a percentage are not comparable, and neither is a ratio.
_UNIT_MARKER = re.compile(r"\s*(%|x\b|bp\b|pp\b)", re.I)

# Words that can stand between a trend verb and the figure it is the size OF,
# without another quantity intervening: "declined ~1%", "fell from 5.19x",
# "grew by 47.2%".
_DELTA_FILLER = frozenset({
    "by", "to", "from", "about", "roughly", "approximately", "around",
    "nearly", "another", "over", "just", "some", "a", "an", "of", "at",
})


def _figure_is_the_change_itself(sentence: str, word: str, first_figure: int) -> bool:
    """True when the figures are the SIZE of the move, not levels either side.

    "bookings declined ~1% FY2025 and 2-3% Q3 FY2026" is a deepening decline,
    and reading its figures as levels says the opposite: 1 then 3, rising,
    contradicting "declined". The same shape covers "grew 47.2%", "fell from
    5.19x" and "declined $0.8B FY2024-FY2025". A delta carries its direction
    in the verb, so there is nothing here for this guard to check.
    """
    start = sentence.lower().find(word) + len(word)
    span = sentence[start:first_figure]
    if _PERIOD_TOKEN.search(span):
        return False
    return all(w in _DELTA_FILLER for w in re.findall(r"[a-z]+", span.lower()))


def _value_after(text: str) -> tuple[float, str, str] | None:
    """The first figure in `text`, as (magnitude, unit class, as written).

    The unit class is what stops the comparison reading "41.3%" against
    "$137,791M" as one quantity moving. The magnitude is scale-normalized so
    "$1.35B" and "$1,351M" compare; the third element is the figure as the
    sentence wrote it, because that is what a reader has to find again.
    """
    match = _DEBATE_NUMBER.search(text)
    if match is None:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None

    written = match.group(0).strip()
    tail = text[match.end():]
    if match.group(2):                       # the regex's own trailing "%"
        return value, "percent", written

    unit = _UNIT_MARKER.match(tail)
    if unit:
        return value, unit.group(1).lower(), written + unit.group(1)

    scale = re.match(r"\s*([A-Za-z]+)", tail)
    if scale and scale.group(1).lower() in _SCALE_SUFFIX:
        return (
            value * _SCALE_SUFFIX[scale.group(1).lower()],
            "magnitude",
            written + scale.group(1),
        )
    return value, "magnitude", written


def _period_value_pairs(sentence: str) -> list[tuple[int, float, str, str, str]]:
    """(year, magnitude, unit class, period as written, figure as written).

    Both orders occur and both have to work: "FY2025 gap of $832M" puts the
    period first, "fell from 5.19x (FY2024) to 2.63x (FY2025)" puts it after.
    Reading only the first shape mis-paired every figure in the second, which
    is how the first version of this guard flagged a correct AVGO claim.
    """
    pairs: list[tuple[int, float, str, str, str]] = []
    periods = list(_PERIOD_TOKEN.finditer(sentence))
    for index, match in enumerate(periods):
        before = sentence[:match.start()].rstrip(" (")
        trailing = _TRAILING_VALUE.search(before)
        attached = _value_after(trailing.group(0)) if trailing else None
        if attached is None:
            stop = periods[index + 1].start() if index + 1 < len(periods) else len(sentence)
            attached = _value_after(sentence[match.end():stop])
        if attached is None:
            return []
        pairs.append(
            (int(match.group(1)), attached[0], attached[1], match.group(0), attached[2])
        )
    return pairs


def contradicted_directions(text: str) -> list[str]:
    """Sentences whose trend word contradicts the figures in the same sentence.

    The gap this closes, found on two NFLX runs a day apart: "a persistent
    OCF/NI gap that is widening — FY2025 gap of $832M versus FY2024's $1,351M
    shortfall". Both figures are correct and both are in the fundamentals
    memo, so `unbacked_figures` cleared them and `check_quotes` had
    nothing to say — and the gap NARROWED. Every other guard here asks where a
    number came from. None reads what the sentence claims the numbers do,
    which is the part a memo's reader acts on.

    Narrow on purpose, and measured rather than assumed: the first version of
    this ran over 36 vault transcripts and returned one true finding and seven
    false ones — a correct AVGO claim whose figures preceded their years, two
    FIG sentences whose trend word governed a different quantity than the one
    the years carried, a markdown table row read as prose, and three risk
    turns where "FY2026 10-K" gave up "10" as a figure. Every condition below
    exists because one of those got through:

      - markdown cells and line breaks END a sentence. A table row is not
        prose and the words either side of a `|` are not one claim.
      - form names (10-K, 10-Q, 8-K, S-1, 20-F) are struck before scanning,
        so "the FY2026 10-K shows" does not offer 10 as FY2026's figure.
      - exactly one direction, from vocabularies that carry one — "improving"
        and "deteriorating" are absent because a deteriorating ratio falls
        while a deteriorating gap rises, and bare "up"/"down" are absent
        because "up to $80 billion" is not a trend claim.
      - the trend word must come BEFORE the figures it is read against. This
        is the one that kills the whole "X fell 8.6% (H1 2026 $141.8M vs H1
        2025 $155.2M) while revenue grew 47.2%" family, where the trailing
        verb belongs to the quantity that has no years attached.
      - exactly two distinct periods, each appearing once, each with a figure,
        the figures sharing a unit class and differing in value.
      - the figures must be LEVELS, not the size of the move. "bookings
        declined ~1% FY2025 and 2-3% Q3 FY2026" is a deepening decline whose
        figures rise; a delta carries its direction in the verb and leaves
        this guard nothing to check. Signed figures are deltas by the same
        argument.

    Everything else is left alone, including trends stated without both
    figures in the same sentence. That silence is the price of a warning a
    reader can trust; the number guard's own history is what a guard costs
    when its flags are usually wrong.
    """
    findings: list[str] = []
    # U+2212 before anything else, exactly as `unbacked_figures` does it:
    # "bookings −1% FY2025" parses as a POSITIVE 1 without this, and the
    # signed-figure rule below never fires on the one shape it exists for.
    scanned = _FORM_NAME.sub("", text.replace("−", "-"))
    for sentence in _SENTENCE_SPLIT.split(scanned):
        words = re.findall(r"[a-z]+", sentence.lower())
        up = [w for w in words if w in _TREND_UP]
        down = [w for w in words if w in _TREND_DOWN]
        if bool(up) == bool(down):          # neither, or both — say nothing
            continue

        pairs = _period_value_pairs(sentence)
        if len(pairs) != 2 or pairs[0][0] == pairs[1][0]:
            continue
        if pairs[0][2] != pairs[1][2] or pairs[0][1] == pairs[1][1]:
            continue

        word = (up or down)[0]
        first_period = _PERIOD_TOKEN.search(sentence)
        if first_period is None or sentence.lower().find(word) > first_period.start():
            continue                        # the verb governs something later
        if min(pairs[0][1], pairs[1][1]) < 0:
            continue                        # a signed figure is a change, not a level
        first_figure = _DEBATE_NUMBER.search(sentence)
        if first_figure and _figure_is_the_change_itself(sentence, word, first_figure.start()):
            continue

        earlier, later = sorted(pairs, key=lambda pair: pair[0])
        actual_up = later[1] > earlier[1]
        if actual_up == bool(up):
            continue

        findings.append(
            f"{word!r} but {later[3]} {later[4]} is "
            f"{'above' if actual_up else 'below'} {earlier[3]} {earlier[4]}"
        )
    return list(dict.fromkeys(findings))


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------

# Formatting, not content: quote characters, whitespace, and the markdown
# markers that carry emphasis rather than meaning ("*", "_", "`").
# Everything with meaning — digits, letters, and the punctuation that changes
# a value (".", ",", "-", ":") — is preserved, so "38.72" still fails to
# match "3.872".
_QUOTE_NOISE = re.compile(r'[\s"\u201c\u201d\u2018\u2019\'*_`]+')


def _norm(text: str) -> str:
    """Project a span onto what a quote actually asserts.

    The technical section of the pack is compact JSON, so the report reads
    `"rsi_14":38.721899422317186` while a debater naturally writes
    `rsi_14: 38.721899422317186` — same field, same value, two characters of
    punctuation apart. Comparing raw, that is a fabricated quote; on the
    first live Haiku turns it flagged 4 claims out of 4, every one of them
    faithful.

    Whitespace goes entirely rather than collapsing to a single space,
    because a quote copied out of a wrapped markdown report carries the wrap.

    Markdown emphasis goes for the same reason, added 2026-08-29 after the
    discrimination probe: the fundamentals report writes "was **not
    effective** as of 2026-06-30" and the debater quoted that sentence with
    the asterisks dropped — a faithful 40-word span reported as a quote not
    in the report, on the one claim the SELL verdict rested on. The markers
    are invisible to a reader and unquotable by construction, so stripping
    them from BOTH sides cannot make a false quote match a real span; it can
    only stop formatting from deciding the answer.
    """
    return _QUOTE_NOISE.sub("", text).lower()


def quote_is_backed(quote: str, source: str) -> bool:
    """True when `quote` appears in `source`, ignoring formatting (see `_norm`)."""
    return _norm(quote) in _norm(source)
