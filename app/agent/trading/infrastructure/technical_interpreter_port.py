from __future__ import annotations

import re
from pathlib import Path

from app.infrastructure.llm import get_client
from app.infrastructure.llm.models import model_for, warn_if_unpriced

# Its own knob (TRADING_TECHNICAL_MODEL), defaulting to the
# project-wide model — which is all this role had before.
TECHNICAL_MODEL = model_for("technical")
warn_if_unpriced(TECHNICAL_MODEL, "technical")

from app.agent.researcher import UsageSummary, _save_output, log_cost
from app.agent.trading.application.technical_indicators import derive_relations
from app.agent.trading.domain.budget import CostEvent
from app.agent.trading.domain.technical_report import TechnicalIndicators, TechnicalReport
from app.agent.trading.infrastructure.cost_log import new_event_id, record_cost_event
from app.agent.trading.infrastructure.evidence import unmatched_by_tolerance

TECHNICAL_INTERPRETER_SYSTEM_PROMPT = """\
You are a technical analysis interpreter. You will be given a set of already-computed
indicator values for a stock. Your job is ONLY to interpret these values in plain
language — trend direction, momentum, overbought/oversold condition, volatility regime,
and volume context.

STRICT RULE: Do not calculate, recompute, restate with different precision, or invent
ANY numeric value. Every number in your response must be one of the numbers given to
you, used exactly as given (you may round for readability, e.g. 62.37 -> "around 62").
If you are not given a value (None), do not guess or fabricate one — say the signal
is unavailable.

USE THE GIVEN RELATIONS: you will be shown a "Computed relations" block stating how
the values compare to each other — whether price is above or below each moving
average, how the moving averages sit relative to one another, and so on. Those
comparisons are computed in code and are authoritative. State them as given. Do not
work out any comparison yourself from the raw numbers, and never contradict the
block. In particular, where price sits relative to a moving average and where the
moving averages sit relative to each other are two different facts — do not
substitute one for the other.

MACD PRECISION: `macd`, `macd_signal`, and `macd_histogram` are three distinct values —
never refer to any of them as just "the MACD". A negative `macd_histogram` means the
MACD line is below its signal line (a bearish crossover), NOT that the MACD line
itself is below zero — those are different conditions and must not be conflated. Name
the specific line you mean: "the MACD line", "the signal line", or "the histogram".

Respond in 3-5 sentences of plain-language interpretation. No preamble, no headers.
"""


async def interpret_indicators(
    ticker: str, indicators: TechnicalIndicators, run_id: str | None = None
) -> tuple[str, list[str], list[str], float | None, CostEvent]:
    client = get_client(TECHNICAL_MODEL)
    relations = "\n".join(f"- {r}" for r in derive_relations(indicators))
    prompt = (
        f"Ticker: {ticker}\n"
        f"Indicators:\n{indicators.model_dump_json(indent=2)}\n\n"
        f"Computed relations (authoritative — state these as given, do not\n"
        f"re-derive them from the numbers above):\n{relations}\n\n"
        "Provide the interpretation now."
    )
    response = await client.messages.create(
        model=TECHNICAL_MODEL,
        # 512 left no room for a model that reasons first: the live ACN/MSFT
        # runs returned an EMPTY interpretation under its own heading, which
        # reads as "nothing to say" rather than as a failure.
        max_tokens=1200,
        system=TECHNICAL_INTERPRETER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    interpretation = "".join(b.text for b in response.content if b.type == "text")

    usage = UsageSummary()
    u = response.usage
    usage.input_tokens = u.input_tokens
    usage.cache_write_tokens = u.cache_creation_input_tokens
    usage.cache_read_tokens = u.cache_read_input_tokens
    usage.output_tokens = u.output_tokens
    event_id = new_event_id("technical")
    cost = log_cost(ticker, "trading-technical", usage, run_id=run_id, event_id=event_id)
    cost_event = record_cost_event(event_id, "technical", usage, TECHNICAL_MODEL, cost)

    flagged = _flag_unmatched_numbers(interpretation, indicators)
    flagged_claims = flag_contradicted_claims(interpretation, indicators)
    return interpretation, flagged, flagged_claims, cost, cost_event


# A claim that something is above/below an N-day average. Non-greedy up to the
# period so "above its 50-day moving average" and "below the 200-day" both
# match, but the search never runs past a sentence boundary.
_PRICE_VS_MA = re.compile(r"\b(above|below)\b[^.;]{0,40}?\b(\d+)-day", re.I)

# The same words describe a different claim when an average is the subject:
# "the 50-day moving average is below the 200-day" compares two averages, and
# checking it against price would flag correct prose. The exclusion has to be
# tight — requiring the average-plus-verb to sit immediately against the
# comparator — because the real failure read "...moving average (around 419)
# but below its 200-day average", where an average appears shortly before
# `below` and yet price is still the subject. A looser rule would have
# skipped exactly the sentence this guard exists to catch.
# Both halves of this pattern were forced by live output, not designed up
# front, and each round of tightening is worth keeping in view:
#
#   1. Enumerating verbs failed. The model wrote "the 50-day average SITTING
#      below the 200-day average" — a participle, not the finite "sits" — and
#      correct prose was reported as a contradiction. Hence up to two bare
#      words instead of a verb list.
#   2. Requiring the noun failed. The next run wrote "the 50-day SITTING below
#      the 200-day", eliding "average" entirely. Hence the noun is optional.
#
# What still separates the two claims is what sits between the average and
# the comparator. In the real error it was "(around 419) but " — parentheses
# and a digit, not bare words — so the exclusion does not fire and the false
# claim is caught. Two words is the whole margin; widening it would start
# swallowing "...50-day average but the price is below its 200-day".
#
# A guard that cries wolf is worse than no guard: it teaches the reader to
# skip it, and then it is not there for the one that matters.
_MA_IS_SUBJECT = re.compile(
    r"\d+-day(?:\s+(?:simple|moving|exponential))*(?:\s+(?:average|ma|sma)s?)?\s+"
    r"(?:\w+\s+){0,2}$",
    re.I,
)


def flag_contradicted_claims(
    text: str, indicators: TechnicalIndicators
) -> list[str]:
    """Flag prose that contradicts a relation computed from the indicators.

    Deliberately narrower than the numbers guard, and a different kind of
    check: it does not ask whether a number is real, it asks whether a claim
    is true. That only works where the ground truth is unambiguous, so it
    covers one family of statement — price versus a moving average — which is
    where the observed error occurred and where "above" and "below" have no
    room for interpretation.

    Flags rather than blocks, like the numbers guard: a false positive should
    cost a reviewer a glance, not a run.
    """
    close = indicators.last_close
    flags: list[str] = []

    for match in _PRICE_VS_MA.finditer(text):
        direction, period = match.group(1).lower(), match.group(2)
        value = getattr(indicators, f"sma_{period}", None)
        if value is None:
            continue  # no such indicator (or not computed) — nothing to check
        if _MA_IS_SUBJECT.search(text[: match.start()]):
            continue  # comparing two averages, not price against one

        actually_above = close > value
        if actually_above == (direction == "above"):
            continue

        flags.append(
            f"claims price is {direction} the {period}-day average, but last "
            f"close {close:.2f} is {'above' if actually_above else 'below'} "
            f"sma_{period} {value:.2f}"
        )

    return flags


def _flag_unmatched_numbers(text: str, indicators: TechnicalIndicators) -> list[str]:
    """Unchanged public signature — the Phase 3 tests keep passing untouched.

    The list-taking form above was extracted so Phase 5's debate guard can
    reuse the percent transforms over numbers scraped out of the analyst
    reports. The alternative — handing this function a fake object with a
    `model_dump()` — would make the debate depend on a duck-typed shim that
    no test covers.
    """
    return unmatched_by_tolerance(
        text,
        [v for v in indicators.model_dump().values() if isinstance(v, (int, float))],
    )


def _format_technical_markdown(report: TechnicalReport) -> str:
    ind = report.indicators
    lines = [
        f"# {report.ticker} — Technical Analysis",
        f"**Date:** {report.as_of_date}",
        f"**Source:** {report.data_source} ({report.bars_used} daily bars)",
        "",
        "## Indicators",
        "",
        "| Indicator | Value |",
        "|---|---|",
        f"| SMA(50) | {ind.sma_50} |",
        f"| SMA(200) | {ind.sma_200} |",
        f"| RSI(14) | {ind.rsi_14} |",
        f"| MACD | {ind.macd} |",
        f"| MACD Signal | {ind.macd_signal} |",
        f"| MACD Histogram | {ind.macd_histogram} |",
        f"| Bollinger Upper | {ind.bb_upper} |",
        f"| Bollinger Mid | {ind.bb_mid} |",
        f"| Bollinger Lower | {ind.bb_lower} |",
        f"| Last Close | {ind.last_close} |",
        f"| Volume vs 20d Avg | {ind.volume_vs_20d_avg} |",
        "",
        "## Interpretation",
        "",
        report.interpretation,
    ]
    if report.interpretation_flagged_claims:
        lines += [
            "",
            "## Contradicted Claims",
            "",
            "Statements above that contradict a relation computed from the "
            "indicators. Unlike a flagged number, these use real values to say "
            "something false — treat the interpretation as unreliable here.",
            "",
        ] + [f"- {c}" for c in report.interpretation_flagged_claims]
    if report.interpretation_flagged_numbers:
        lines += [
            "",
            "## Flagged Numbers",
            "",
            "Numbers in the interpretation that could not be matched back to a "
            "retrieved indicator value. Review before relying on them.",
            "",
            ", ".join(report.interpretation_flagged_numbers),
        ]
    return "\n".join(lines)


def save_technical_report(report: TechnicalReport, cost_usd: float | None = None) -> Path:
    content = _format_technical_markdown(report)
    return _save_output(content, report.ticker.upper(), "technical", cost_usd=cost_usd)
