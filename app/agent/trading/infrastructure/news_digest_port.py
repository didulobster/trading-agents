from __future__ import annotations

import json
from typing import Any

from anthropic import AsyncAnthropic

from app.agent.researcher import AGENT_MODEL, UsageSummary, log_cost
from app.agent.trading.domain.errors import VendorError
from app.agent.trading.domain.news_digest import NewsItem

BATCH_SIZE = 15
DIGEST_MAX_TOKENS = 1500
NEWS_BUDGET_USD = 0.20

VALID_SENTIMENTS = {"positive", "negative", "neutral"}

# Design rule: the model receives numbered articles and returns only
# {index, summary, sentiment}. Python joins the result back onto the trusted
# vendor metadata by index. The model never emits a headline, a date, a
# source, or a URL — same move that fixed sbc_pct_of_revenue: don't let the
# model retype data it can copy wrong.
SYSTEM_PROMPT = """You summarize financial news articles for an equity research pipeline.

You will receive numbered articles, each marked [N]. For EACH article, return one object:
  index    - the article's number N as a bare JSON integer: 0, not "0" and not "[0]"
  summary  - ONE sentence, max 25 words, describing what the article reports
  sentiment - exactly one of: positive, negative, neutral

Rules:
- Sentiment is about the likely effect on the company's equity, not the tone of the writing.
- "neutral" is the correct answer for routine coverage, analyst-roundup pieces, and
  anything where the direction is genuinely unclear. Do not force a direction.
- Summarize ONLY what the provided text says. Do not add context, do not add figures
  that are not in the text, do not speculate about causes or consequences.
- Return one object per input article. Never merge, skip, or invent articles.
- Return a JSON array and nothing else. No prose, no markdown fences.
"""


def _render_batch(articles: list[dict[str, Any]]) -> str:
    lines = []
    for i, a in enumerate(articles):
        body = (a.get("summary") or "").strip()[:600]   # truncate long bodies
        lines.append(f"[{i}] HEADLINE: {a.get('headline', '')}\n    BODY: {body}")
    return "\n\n".join(lines)


async def _summarize_batch(
    client: AsyncAnthropic, articles: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], Any]:
    resp = await client.messages.create(
        model=AGENT_MODEL,
        max_tokens=DIGEST_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _render_batch(articles)}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise VendorError(f"Haiku returned non-JSON digest: {e}") from e
    if not isinstance(parsed, list):
        raise VendorError(
            f"Haiku digest is {type(parsed).__name__}, expected a JSON array"
        )

    return parsed, resp.usage


def _parse_index(raw: Any) -> int:
    """Coerce the model's `index` to an int, tolerating the bracketed form.

    Observed on the first live run (FIG, 2026-08-21): a 3-article batch came
    back with "index": "[0]", "[1]", "[2]" — the model echoing the `[0]`
    marker this module renders in the prompt rather than the bare integer.
    Every one of those articles was dropped, and all three happened to be the
    most on-topic stories in the batch.

    The bracketed form is unambiguous, so strip it rather than rejecting it:
    a rejected index costs a real article, which is the exact data loss the
    join exists to prevent. Genuinely ambiguous values still raise and get
    flagged — bools (isinstance(True, int) is True, and int(True) == 1 would
    silently claim index 1) and non-integral floats (int(1.7) == 1 would
    silently claim the wrong article) are rejected rather than guessed at.
    """
    if isinstance(raw, bool):
        raise ValueError(f"bool {raw!r} is not an article index")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if not raw.is_integer():
            raise ValueError(f"non-integral index {raw!r}")
        return int(raw)
    if isinstance(raw, str):
        return int(raw.strip().strip("[]").strip())
    raise TypeError(f"index of type {type(raw).__name__}")


def _join(
    articles: list[dict[str, Any]], parsed: list[dict[str, Any]]
) -> tuple[list[NewsItem], list[str]]:
    """Join LLM output back onto trusted metadata by index.

    Anything the model got structurally wrong is flagged, not silently
    absorbed. A missing index means an article vanished from the digest —
    that is data loss, and it must be visible. These are structural checks
    (index present / in range / unique, enum valid), which unlike the Phase 3
    regex-over-prose guard have no false-positive problem.
    """
    by_index: dict[int, dict[str, Any]] = {}
    issues: list[str] = []

    for obj in parsed:
        try:
            idx = _parse_index(obj["index"])
        except (KeyError, TypeError, ValueError):
            issues.append(f"unparseable index in {obj!r}")
            continue
        if not 0 <= idx < len(articles):
            issues.append(f"index {idx} out of range (batch of {len(articles)})")
            continue
        if idx in by_index:
            issues.append(f"duplicate index {idx}")
            continue
        by_index[idx] = obj

    items: list[NewsItem] = []
    for i, art in enumerate(articles):
        obj = by_index.get(i)
        if obj is None:
            issues.append(f"missing index {i}: {art.get('headline', '')[:60]!r}")
            continue

        sentiment = str(obj.get("sentiment", "")).strip().lower()
        if sentiment not in VALID_SENTIMENTS:
            issues.append(f"index {i}: invalid sentiment {sentiment!r} -> neutral")
            sentiment = "neutral"

        items.append(
            NewsItem(
                headline=art.get("headline", ""),   # from vendor, not model
                published_date=art["_pub_date"],    # from vendor, not model
                source=art.get("source", "unknown"),
                url=art.get("url", ""),
                summary=str(obj.get("summary", "")).strip(),
                sentiment=sentiment,
            )
        )

    return items, issues


def _assert_within_budget(cost: float | None) -> None:
    """Typo-catcher, not the real constraint: at ~$0.0003/article the cap in
    news_data_port (MAX_ARTICLES) binds ~10x before this budget does. What
    this catches is a model-string change that silently routes the digest to
    an expensive model."""
    if cost is not None and cost > NEWS_BUDGET_USD:
        raise AssertionError(
            f"news digest cost ${cost:.4f} exceeds the ${NEWS_BUDGET_USD:.2f} "
            f"per-run budget — check AGENT_MODEL routing before rerunning"
        )


async def build_digest(
    articles: list[dict[str, Any]], ticker: str
) -> tuple[list[NewsItem], list[str], float | None]:
    """Batch the cleaned articles through Haiku and join by index.

    Usage is summed across batches into ONE cost-log line per run, so the
    per-run budget check doesn't have to reassemble per-batch lines.
    """
    if not articles:
        return [], [], None

    client = AsyncAnthropic()
    usage = UsageSummary()
    items: list[NewsItem] = []
    issues: list[str] = []

    for start in range(0, len(articles), BATCH_SIZE):
        batch = articles[start : start + BATCH_SIZE]
        parsed, batch_usage = await _summarize_batch(client, batch)
        usage.input_tokens += batch_usage.input_tokens
        usage.cache_write_tokens += batch_usage.cache_creation_input_tokens or 0
        usage.cache_read_tokens += batch_usage.cache_read_input_tokens or 0
        usage.output_tokens += batch_usage.output_tokens

        batch_items, batch_issues = _join(batch, parsed)
        items.extend(batch_items)
        issues.extend(batch_issues)

    cost = log_cost(ticker, "trading-news", usage)
    _assert_within_budget(cost)
    return items, issues, cost
