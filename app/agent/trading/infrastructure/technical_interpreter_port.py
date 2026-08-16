from __future__ import annotations

import re

from anthropic import AsyncAnthropic

from app.agent.researcher import AGENT_MODEL, UsageSummary, log_cost
from app.agent.trading.domain.technical_report import TechnicalIndicators

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

Respond in 3-5 sentences of plain-language interpretation. No preamble, no headers.
"""


async def interpret_indicators(ticker: str, indicators: TechnicalIndicators) -> tuple[str, list[str]]:
    client = AsyncAnthropic()
    prompt = (
        f"Ticker: {ticker}\n"
        f"Indicators:\n{indicators.model_dump_json(indent=2)}\n\n"
        "Provide the interpretation now."
    )
    response = await client.messages.create(
        model=AGENT_MODEL,
        max_tokens=512,
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
    log_cost(ticker, "trading-technical", usage)

    flagged = _flag_unmatched_numbers(interpretation, indicators)
    return interpretation, flagged


def _flag_unmatched_numbers(text: str, indicators: TechnicalIndicators) -> list[str]:
    """Cheap guard, not a full verifier: extract numbers mentioned in the interpretation
    and check each is within rounding tolerance of some value actually in `indicators`.
    Flags (doesn't block) anything that doesn't match — surfaced in TechnicalReport for
    human review, same spirit as the 'Unverified Figures' section in memo_verifier.

    Will produce false positives on narrative numbers that reference thresholds rather
    than indicator values themselves (e.g. "RSI above 70") — treat this as a review
    signal, not an auto-reject.

    Two known transformations are normalized before flagging, each patched from a real
    false positive rather than designed upfront — coverage is only as good as the
    phrasing actually tested, not something derivable from first principles:

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
    """
    known_values = [v for v in indicators.model_dump().values() if isinstance(v, (int, float))]
    text_no_periods = re.sub(r"\b\d+-day\b", "", text)

    flagged: list[str] = []

    percent_pattern = re.compile(r"(-?\d+\.?\d*)%")
    for m in percent_pattern.findall(text_no_periods):
        ratio = float(m) / 100
        if not any(abs(ratio - kv) <= max(0.01, abs(kv) * 0.02) for kv in known_values):
            flagged.append(f"{m}%")
    text_no_percents = percent_pattern.sub("", text_no_periods)

    for m in re.findall(r"-?\d+\.?\d*", text_no_percents):
        val = float(m)
        if not any(abs(val - kv) <= max(0.5, abs(kv) * 0.02) for kv in known_values):
            flagged.append(m)

    return flagged
