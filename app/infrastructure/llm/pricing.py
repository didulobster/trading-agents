"""Cost config — price per million tokens, keyed by model id.

Lives here rather than in `researcher.py` because pricing is a property of
the provider, not of the research agent: three ports and the budget
assertions all read this table, and `researcher.py` re-exports it as
`_MODEL_PRICING` so every existing import keeps working.

Why a table at all: the per-turn budget assertions are the only thing
standing between a prompt-bloat regression and an unbounded bill, and an
unpriced model makes every turn cost `None` — which sums to 0.00 and can
never trip the guard. A model that is not in here is not merely
un-costed, it is un-guarded, which is why each port shouts at import when
its configured model is missing.

Adding a model: either add an entry below, or — without touching code —
set `LLM_PRICING_OVERRIDES` to a JSON object of the same shape. The env
var is merged over the table at import, so it can both add new models and
correct a rate that moved after this file was written.

    LLM_PRICING_OVERRIDES='{"deepseek-chat":{"input":0.27,"output":1.10,
                            "cache_write":0.0,"cache_read":0.07}}'

All four keys are required per model. `cache_write` is the rate charged to
PUT tokens in the cache and `cache_read` the rate to hit it; a provider
that caches automatically and bills nothing for the write sets
`cache_write` to 0.0 rather than omitting it.
"""

from __future__ import annotations

import json
import os

# Per million tokens, USD.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "output": 5.00,
        "cache_write": 1.25,
        "cache_read": 0.10,
    },
    "claude-sonnet-4-5-20250929": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    # Sonnet 5 carries an introductory $2/$10 through 2026-08-31 and reverts
    # to $3/$15 on Sep 1. Budgeted at the standing rate deliberately: pricing
    # the intro here would make every debate-cost assertion start failing on
    # a date nobody was watching, and over-estimating cost fails safe.
    "claude-sonnet-5": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    # DeepSeek V3 (`deepseek-chat`) and R1 (`deepseek-reasoner`).
    #
    # DeepSeek caches automatically — there is no `cache_control` to set and
    # no separate charge to write, so `cache_write` is 0.0 and the discount
    # shows up entirely as `cache_read`. The shim maps their
    # `prompt_cache_miss_tokens` to `input` and `prompt_cache_hit_tokens` to
    # `cache_read`, so the two never double-count (their `prompt_tokens`
    # is the sum of both, and is deliberately NOT what gets priced).
    #
    # DeepSeek has repriced more than once and runs promotional rates.
    # VERIFY against https://api-docs.deepseek.com/quick_start/pricing
    # before trusting a budget assertion built on these numbers; correct
    # them via LLM_PRICING_OVERRIDES rather than by editing here, so a rate
    # change is a config change.
    "deepseek-chat": {
        "input": 0.27,
        "output": 1.10,
        "cache_write": 0.0,
        "cache_read": 0.07,
    },
    "deepseek-reasoner": {
        "input": 0.55,
        "output": 2.19,
        "cache_write": 0.0,
        "cache_read": 0.14,
    },
}

_REQUIRED_KEYS = frozenset({"input", "output", "cache_write", "cache_read"})


def _load_overrides() -> None:
    """Merge `LLM_PRICING_OVERRIDES` over the table.

    Raises on malformed input rather than falling back to the built-in
    rates: a typo that silently leaves the old price in place would make
    the budget guard quietly wrong, which is the one failure this whole
    table exists to prevent.
    """
    raw = os.getenv("LLM_PRICING_OVERRIDES")
    if not raw:
        return
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("LLM_PRICING_OVERRIDES must be a JSON object of model -> rates")
    for model, rates in parsed.items():
        missing = _REQUIRED_KEYS - set(rates or {})
        if missing:
            raise ValueError(
                f"LLM_PRICING_OVERRIDES[{model!r}] is missing {sorted(missing)}; "
                f"all of {sorted(_REQUIRED_KEYS)} are required"
            )
        MODEL_PRICING[model] = {k: float(rates[k]) for k in _REQUIRED_KEYS}


_load_overrides()
