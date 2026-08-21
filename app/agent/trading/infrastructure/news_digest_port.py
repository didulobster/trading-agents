from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from app.agent.researcher import AGENT_MODEL, UsageSummary, _save_output, log_cost
from app.agent.trading.domain.errors import VendorError
from app.agent.trading.domain.news_digest import (
    AGGREGATED_RELEVANCE,
    NewsDigest,
    NewsItem,
    SentimentSummary,
)

BATCH_SIZE = 15
DIGEST_MAX_TOKENS = 1500
NEWS_BUDGET_USD = 0.20

VALID_SENTIMENTS = {"positive", "negative", "neutral"}
VALID_RELEVANCE = {"primary", "mentioned", "unrelated"}

# Design rule: the model receives numbered articles and returns only
# {index, summary, sentiment}. Python joins the result back onto the trusted
# vendor metadata by index. The model never emits a headline, a date, a
# source, or a URL — same move that fixed sbc_pct_of_revenue: don't let the
# model retype data it can copy wrong.
SYSTEM_PROMPT = """You summarize financial news articles for an equity research pipeline.

The user message names one COMPANY UNDER ANALYSIS, then gives numbered articles
marked [N]. The articles come from a vendor feed tagged with that company's
ticker, but many of them turn out to be about other companies, sector trends, or
the market as a whole. Judging that is part of your job.

For EACH article, return one object:
  index     - the article's number N as a bare JSON integer: 0, not "0" and not "[0]"
  summary   - ONE sentence, max 25 words, describing what the article reports
  relevance - exactly one of: primary, mentioned, unrelated
  sentiment - exactly one of: positive, negative, neutral

Relevance is about the COMPANY UNDER ANALYSIS, and nothing else:
- "primary"   - the article is substantially about that company: its results,
                products, guidance, management, stock, or an event directly
                involving it. An analyst rating or price target on that company
                counts as primary.
- "mentioned" - the company appears or is clearly implicated, but the article is
                mainly about something else: a sector trend, an index move, a
                competitor, a partner, or a broad market column.
- "unrelated" - the company is not meaningfully involved at all. A feed tag is
                not involvement. If the article is about a different company and
                the company under analysis plays no part, it is unrelated.

Sentiment is also about the COMPANY UNDER ANALYSIS:
- Score the likely effect on THAT company's equity, not the tone of the writing
  and not the effect on whichever company the article happens to be about.
- If relevance is "unrelated", sentiment must be "neutral" — an article that does
  not involve the company cannot be evidence about it.
- "neutral" is the correct answer for routine coverage, analyst-roundup pieces, and
  anything where the direction is genuinely unclear. Do not force a direction.

Other rules:
- Summarize ONLY what the provided text says. Do not add context, do not add figures
  that are not in the text, do not speculate about causes or consequences.
- Return one object per input article. Never merge, skip, or invent articles.
- Return a JSON array and nothing else. No prose, no markdown fences.
"""


def _render_batch(articles: list[dict[str, Any]], ticker: str) -> str:
    """The ticker heads the batch because relevance and sentiment are both
    judged against it. Without it the model scored each article against
    whichever company that article was about, which is how a Netflix
    sell-off ended up as a data point in MSFT's aggregate."""
    lines = [f"COMPANY UNDER ANALYSIS: {ticker.upper()}", ""]
    for i, a in enumerate(articles):
        body = (a.get("summary") or "").strip()[:600]   # truncate long bodies
        lines.append(f"[{i}] HEADLINE: {a.get('headline', '')}\n    BODY: {body}")
    return "\n".join(lines[:2]) + "\n" + "\n\n".join(lines[2:])


async def _summarize_batch(
    client: AsyncAnthropic, articles: list[dict[str, Any]], ticker: str
) -> tuple[list[dict[str, Any]], Any]:
    resp = await client.messages.create(
        model=AGENT_MODEL,
        max_tokens=DIGEST_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _render_batch(articles, ticker)}],
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

        # Degrades to "mentioned", the middle value, rather than either
        # extreme: "unrelated" would drop a real article out of the aggregate
        # over a formatting slip, and "primary" would admit possible noise.
        # "mentioned" keeps the item in the digest for audit while holding it
        # out of a primary-only aggregate, and the issue makes it visible.
        relevance = str(obj.get("relevance", "")).strip().lower()
        if relevance not in VALID_RELEVANCE:
            issues.append(f"index {i}: invalid relevance {relevance!r} -> mentioned")
            relevance = "mentioned"

        items.append(
            NewsItem(
                headline=art.get("headline", ""),   # from vendor, not model
                published_date=art["_pub_date"],    # from vendor, not model
                source=art.get("source", "unknown"),
                url=art.get("url", ""),
                summary=str(obj.get("summary", "")).strip(),
                sentiment=sentiment,
                relevance=relevance,
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
        parsed, batch_usage = await _summarize_batch(client, batch, ticker)
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


def _format_sentiment_markdown(
    digest: NewsDigest,
    summary: SentimentSummary,
    issues: list[str] | None = None,
) -> str:
    """Render the digest and its aggregate for the vault.

    Every number that qualifies the signal is on the page, not just the
    signal: a +0.60 over four articles and a +0.60 over forty are different
    claims, and the reader cannot tell them apart from the score.
    """
    counted = [i for i in digest.items if i.relevance in AGGREGATED_RELEVANCE]
    other = [i for i in digest.items if i.relevance not in AGGREGATED_RELEVANCE]
    window_days = (digest.as_of_date - digest.window_start).days

    lines = [
        f"# {digest.ticker} — News Sentiment",
        f"**Analysis date (as-of):** {digest.as_of_date}",
        f"**Window:** {digest.window_start} → {digest.as_of_date} ({window_days} days)",
        f"**Source:** {digest.data_source}",
        "",
        "## Signal",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Net score | {summary.net_score:+.3f} |",
        f"| Positive | {summary.positive} |",
        f"| Negative | {summary.negative} |",
        f"| Neutral | {summary.neutral} |",
        f"| Articles counted | {summary.article_count} |",
        f"| Excluded as not primarily about {digest.ticker} | "
        f"{summary.excluded_by_relevance} |",
        "",
    ]

    caveats = []
    if summary.article_count == 0:
        caveats.append(
            "**No articles were primarily about this company.** A net score of "
            "0.000 here is an absence of evidence, not neutral evidence — do not "
            "read it as the market being indifferent."
        )
    elif summary.article_count < 5:
        caveats.append(
            f"**Thin sample.** The score rests on {summary.article_count} "
            f"article(s); a single item moves it materially."
        )
    if digest.truncated_by_cap:
        caveats.append(
            f"**Truncated.** The vendor returned {digest.raw_article_count} "
            f"articles and the cap kept the newest {len(digest.items)}, so this "
            f"digest is a sample of the window rather than all of it. Coverage "
            f"is skewed toward the most recent days."
        )
    if issues:
        caveats.append(
            f"**{len(issues)} digest integrity issue(s)** — see the section below; "
            f"articles may be missing from this digest."
        )
    if caveats:
        lines += ["## Caveats", ""] + [f"- {c}" for c in caveats] + [""]

    lines += [
        "## Coverage",
        "",
        "| Stage | Count |",
        "|---|---|",
        f"| Returned by vendor | {digest.raw_article_count} |",
        f"| Dropped: outside the window | {digest.dropped_out_of_window} |",
        f"| Dropped: missing/zero timestamp | {digest.dropped_missing_date} |",
        f"| Kept after filter, dedup and cap | {digest.deduped_count} |",
        f"| In this digest | {len(digest.items)} |",
        "",
    ]

    lines += [f"## Articles about {digest.ticker} ({len(counted)})", ""]
    if counted:
        for i in counted:
            lines += [
                f"### [{i.published_date}] {i.headline}",
                f"*{i.sentiment}* · {i.source} · [link]({i.url})",
                "",
                i.summary,
                "",
            ]
    else:
        lines += ["_None. Nothing in the window was primarily about this company._", ""]

    if other:
        lines += [
            f"## Other coverage in the feed ({len(other)})",
            "",
            "Tagged with this ticker by the vendor but not primarily about the "
            "company, so excluded from the score. Kept for context.",
            "",
            "| Date | Relevance | Sentiment | Headline |",
            "|---|---|---|---|",
        ]
        for i in other:
            headline = i.headline.replace("|", "\\|")
            lines.append(
                f"| {i.published_date} | {i.relevance} | {i.sentiment} | {headline} |"
            )
        lines.append("")

    if issues:
        lines += [
            "## Digest integrity issues",
            "",
            "Structural problems in the model's response, surfaced rather than "
            "absorbed. A missing index means an article was dropped from the digest.",
            "",
        ] + [f"- {i}" for i in issues] + [""]

    return "\n".join(lines)


def save_sentiment_report(
    digest: NewsDigest,
    summary: SentimentSummary,
    issues: list[str] | None = None,
    cost_usd: float | None = None,
    provenance: str | None = None,
) -> Path:
    content = _format_sentiment_markdown(digest, summary, issues)
    return _save_output(
        content,
        digest.ticker.upper(),
        "sentiment",
        cost_usd=cost_usd,
        provenance=provenance,
    )
