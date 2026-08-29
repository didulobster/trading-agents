"""Rendering of the two vault artifacts the trading CLI writes.

These assert the judgement calls, not the layout: which caveats appear,
which articles are counted, and that a placeholder is never presented as a
finding. Wording is checked loosely so cosmetic edits don't fail the suite.
"""

from __future__ import annotations

import json
from datetime import date

from app.agent.trading.domain.decision_memo import DecisionMemo, Verdict, EvidenceQuality
from app.agent.trading.domain.news_digest import NewsDigest, NewsItem, SentimentSummary
from app.agent.trading.infrastructure.decision_memo_port import _format_memo_markdown
from app.agent.trading.infrastructure.news_digest_port import _format_sentiment_markdown

AS_OF = date(2026, 8, 22)


def _item(headline: str, sentiment: str, relevance: str) -> NewsItem:
    return NewsItem(
        headline=headline,
        published_date=AS_OF,
        source="wire",
        url="https://example.com/x",
        summary=f"summary of {headline}",
        sentiment=sentiment,
        relevance=relevance,
    )


def _digest(items: list[NewsItem], *, raw: int = 10, truncated: bool = False) -> NewsDigest:
    return NewsDigest(
        ticker="AVGO",
        as_of_date=AS_OF,
        window_start=date(2026, 8, 8),
        items=items,
        raw_article_count=raw,
        deduped_count=len(items),
        dropped_out_of_window=0,
        dropped_missing_date=0,
        truncated_by_cap=truncated,
    )


def _summary(pos=0, neg=0, neu=0, excluded=0) -> SentimentSummary:
    total = pos + neg + neu
    return SentimentSummary(
        ticker="AVGO",
        as_of_date=AS_OF,
        positive=pos,
        negative=neg,
        neutral=neu,
        net_score=(pos - neg) / total if total else 0.0,
        article_count=total,
        excluded_by_relevance=excluded,
    )


def test_only_primary_articles_appear_in_the_counted_section():
    items = [
        _item("Broadcom beats", "positive", "primary"),
        _item("Sector roundup", "negative", "mentioned"),
        _item("Ferrari news", "negative", "unrelated"),
    ]

    md = _format_sentiment_markdown(_digest(items), _summary(pos=1, excluded=2))

    counted, other = md.split("## Other coverage")
    assert "Broadcom beats" in counted
    assert "Sector roundup" not in counted
    assert "Ferrari news" not in counted
    # excluded articles are still listed, so the reader can see what was
    # dropped rather than trusting that the filter was right
    assert "Sector roundup" in other and "Ferrari news" in other


def test_empty_result_is_labelled_absence_of_evidence():
    md = _format_sentiment_markdown(
        _digest([_item("Ferrari news", "positive", "unrelated")]), _summary(excluded=1)
    )

    assert "absence of evidence" in md
    assert "Nothing in the window was primarily about this company" in md


def test_thin_sample_is_flagged_but_a_healthy_one_is_not():
    thin = _format_sentiment_markdown(
        _digest([_item("a", "positive", "primary")]), _summary(pos=1)
    )
    healthy = _format_sentiment_markdown(
        _digest([_item(str(i), "positive", "primary") for i in range(8)]),
        _summary(pos=8),
    )

    assert "Thin sample" in thin
    assert "Thin sample" not in healthy


def test_truncation_is_surfaced_as_a_caveat_with_both_counts():
    md = _format_sentiment_markdown(
        _digest([_item("a", "positive", "primary")], raw=247, truncated=True),
        _summary(pos=1),
    )

    assert "Truncated" in md
    assert "247" in md
    assert "sample of the window" in md


def test_digest_issues_are_shown_not_swallowed():
    md = _format_sentiment_markdown(
        _digest([_item("a", "positive", "primary")]),
        _summary(pos=1),
        issues=["missing index 3: 'Broadcom raises guidance'"],
    )

    assert "integrity issue" in md
    assert "missing index 3" in md


def test_headline_pipes_do_not_break_the_excluded_table():
    md = _format_sentiment_markdown(
        _digest([_item("Chips | AI | Everything", "neutral", "unrelated")]),
        _summary(excluded=1),
    )

    row = next(line for line in md.splitlines() if "Chips" in line)
    # escaped pipes still contain the character, so count only the ones that
    # actually delimit cells: 4 columns => 5 delimiters
    assert row.replace(r"\|", "").count("|") == 5
    assert row.count(r"\|") == 2


# ---------------------------------------------------------------------------
# Decision memo
# ---------------------------------------------------------------------------

def _memo(**over) -> DecisionMemo:
    base = dict(
        ticker="AVGO",
        bull_case="STUB",
        bear_case="STUB",
        research_thesis="STUB",
        risk_debate_summary="STUB — Phase 6",
        technical_signal="RSI at 36.2 indicates oversold conditions.",
        reasoning="STUB — synthesis logic not yet implemented.",
        watch_items=[],
        verdict=Verdict.HOLD,
        evidence_quality=EvidenceQuality(score=0.0, analyst_coverage=1.0, panel_dispersion=0.0, guard_flags=0),
        data_as_of_date=AS_OF,
        data_gaps=["debate/risk nodes are still stubs"],
        assumptions=[],
        evidence=[],
    )
    base.update(over)
    return DecisionMemo(**base)


def test_stub_fields_are_marked_not_presented_as_findings():
    md = _format_memo_markdown(_memo())

    bull = md.split("## Bull case")[1].split("##")[0]
    assert "Not yet implemented" in bull
    # the bare placeholder never appears as if it were prose
    assert "\nSTUB\n" not in md.split("## Raw memo")[0]
    # real content passes through untouched
    assert "RSI at 36.2 indicates oversold conditions." in md


def test_zero_confidence_memo_carries_an_extreme_caution_warning():
    md = _format_memo_markdown(_memo())
    assert "extreme caution" in md
    assert "0.00" in md

    real = _format_memo_markdown(
        _memo(evidence_quality=EvidenceQuality(score=0.72, analyst_coverage=1.0, panel_dispersion=0.0, guard_flags=0), reasoning="Cash generation is durable.")
    )
    assert "extreme caution" not in real


def test_raw_json_block_preserves_the_unedited_memo():
    memo = _memo()
    md = _format_memo_markdown(memo)

    block = md.split("```json")[1].split("```")[0]
    assert json.loads(block) == memo.model_dump(mode="json")
    # the stubs survive verbatim in the raw block even though the prose
    # sections relabel them
    assert json.loads(block)["bull_case"] == "STUB"


def test_evidence_quality_is_shown_with_its_components_not_as_a_band():
    """The old line read `**Confidence:** HIGH (0.93)`. Both halves invited a
    reader to take an input-quality score for a probability the verdict is
    right — see `EvidenceQuality`. It now names what it measures and shows
    the three terms, so a reader can see that analyst coverage is pinned at
    1.00 on every full run and carries 0.6 of the composite."""
    rendered = _format_memo_markdown(
        _memo(evidence_quality=EvidenceQuality(
            score=0.93, analyst_coverage=1.0, panel_dispersion=0.08, guard_flags=2
        ))
    )

    assert "**Evidence quality:** 0.93" in rendered
    assert "analyst coverage 1.00" in rendered
    assert "panel dispersion 0.08" in rendered
    assert "2 guard flags" in rendered
    assert "Confidence" not in rendered
    assert "HIGH" not in rendered


def test_verdict_agreement_is_rendered_beside_evidence_quality_when_a_vote_happened():
    voted = _format_memo_markdown(
        _memo(
            evidence_quality=EvidenceQuality(
                score=0.97, analyst_coverage=1.0, panel_dispersion=0.05, guard_flags=1
            ),
            verdict_samples=["sell", "hold", "sell"],
            verdict_agreement=0.67,
        )
    )
    assert "**Verdict agreement:** 2 of 3 (0.67)" in voted
    # Shown side by side and NOT reconciled: 0.97 evidence quality on a 2-1
    # split is exactly the pair that used to be one self-contradictory number.
    assert "**Evidence quality:** 0.97" in voted

    # None is not 1.0: a memo whose verdict was never put to a vote has not
    # achieved unanimity, and the line is omitted rather than faked.
    unvoted = _format_memo_markdown(_memo())
    assert "Verdict agreement" not in unvoted
    assert "1 guard flag)" in voted and "1 guard flags" not in voted

def test_gaps_are_rendered_and_counted():
    md = _format_memo_markdown(_memo(data_gaps=["a", "b"]))
    assert "## Data gaps (2)" in md
    assert "- a" in md and "- b" in md

    empty = _format_memo_markdown(_memo(data_gaps=[]))
    assert "## Data gaps (0)" in empty
    assert "_None recorded._" in empty


def test_watch_items_are_rendered_and_counted():
    md = _format_memo_markdown(_memo(watch_items=["closes below 850", "Q3 margin print"]))
    assert "## Watch items (2)" in md
    assert "- closes below 850" in md and "- Q3 margin print" in md

    empty = _format_memo_markdown(_memo(watch_items=[]))
    assert "## Watch items (0)" in empty
    assert "_None recorded._" in empty


def test_verdict_line_names_the_risk_judge_as_sole_decision_maker():
    """No more override/affirm banner — removed alongside
    ResearchManagerPayload.preliminary_verdict (2026-08-26, code review):
    the Risk Judge's verdict is the memo's only verdict, nothing to compare
    it against."""
    md = _format_memo_markdown(_memo(verdict=Verdict.SELL))
    assert "Verdict (Risk Judge, sole decision maker):** SELL" in md
    assert "OVERRIDDEN" not in md
    assert "affirmed" not in md


def test_a_sampled_verdict_shows_the_split_not_a_bare_label():
    """Added 2026-08-26 alongside majority-of-N sampling: when
    `verdict_samples` is populated, the verdict was never any ONE Risk
    Judge call's alone, so the old "sole decision maker" line would
    misattribute it. A reader should see the actual samples the verdict
    was computed from."""
    md = _format_memo_markdown(
        _memo(verdict=Verdict.SELL, verdict_samples=["hold", "sell", "sell"])
    )
    assert "Risk Judge, sole decision maker" not in md
    assert "**Verdict:** SELL (majority of 3 samples: hold, sell, sell)" in md


def test_an_unresolved_verdict_names_itself_as_no_majority():
    md = _format_memo_markdown(
        _memo(verdict=Verdict.UNRESOLVED, verdict_samples=["buy", "sell", "hold"])
    )
    assert "**Verdict:** UNRESOLVED (no majority of 3 samples: buy, sell, hold)" in md
