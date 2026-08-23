"""Structural guarantees of the analyst prompt's red-flag rubric.

Three runs on the same ticker, same filings, same day returned
INSUFFICIENT_EVIDENCE, then "TIER CLEAN with 1 cyclical red flag", then
"CLEAN, 0 red flags". The evidence was identical and consistent in all
three; only the classification moved. The cause was that the Assessment
section demanded each flag name "the specific threshold from that item's
rubric" while nine of the twelve checklist items had no threshold at all.

These assert the properties that prevent that recurring. They cannot test
the model's judgement — only that the prompt still gives it something
mechanical to apply, so a future edit cannot quietly delete a threshold and
return the verdict to a coin flip.
"""

from __future__ import annotations

import re

from app.agent.prompts import ANALYST_SYSTEM_PROMPT as PROMPT

RUBRIC = PROMPT.split("## Red-flag rubric")[1].split("## Assessment")[0]


def test_every_checklist_item_has_a_threshold():
    """The defect itself: a rubric that skips an item sends the model back to
    inventing a threshold for it."""
    numbered = {int(m) for m in re.findall(r"^(\d+)\.", RUBRIC, re.M)}

    assert numbered == set(range(1, 13)), f"missing rubric for items {sorted(set(range(1,13)) - numbered)}"


def test_multi_part_items_keep_their_sub_parts():
    """Items 6, 10 and 11 are multi-part in the checklist, and each part has
    its own failure mode — collapsing them loses thresholds."""
    for item, parts in (("6", ("(a)", "(b)")), ("10", ("(a)", "(b)", "(c)")), ("11", ("(a)", "(b)"))):
        body = re.split(rf"^{item}\.", RUBRIC, flags=re.M)[1]
        body = re.split(r"^\d+\.", body, flags=re.M)[0]
        for part in parts:
            assert part in body, f"item {item} lost sub-part {part}"


def test_thresholds_are_stated_as_comparisons_not_adjectives():
    """A threshold has to be checkable against figures this review already
    retrieves. Asserted by shape rather than parsed: the rubric should carry
    quantified cutoffs and explicit comparisons, not adjectives."""
    quantified = re.findall(
        r"\d+(?:\.\d+)?\s*(?:%|percent|percentage points|basis points|x\b)", RUBRIC
    )
    assert len(quantified) >= 5, f"only {len(quantified)} quantified cutoffs: {quantified}"

    for comparison in ("exceeds", "year over year", "more than"):
        assert comparison in RUBRIC, comparison

    # the vocabulary that leaves a criterion unfalsifiable
    for vague in ("significant", "material concern", "worrying", "as appropriate"):
        assert vague not in RUBRIC.lower(), f"vague criterion reintroduced: {vague}"


def test_an_explanation_cannot_cancel_a_flag():
    """The exact judgement that swung between runs: one call treated a
    capex-driven FCF fall as explained-and-therefore-not-a-flag, the other
    counted it. The rubric has to settle that, and settle it in the direction
    that keeps the flag."""
    assert "NEVER cancels a flag" in RUBRIC
    assert "cyclical" in RUBRIC and "not omitted" in RUBRIC


def test_the_structural_cyclical_tag_has_a_test_and_a_default():
    """Measured after the rubric landed: all three runs raised the item 1 FCF
    flag, but one tagged the same capex driver structural and two tagged it
    cyclical. Keeping the flag was the fix; the tag was still an impression.
    It now turns on whether the filer itself says the driver abates, with a
    stated default so silence cannot break the tie two ways."""
    assert "ONLY when the filer itself states" in RUBRIC
    assert "Silence defaults to structural" in RUBRIC
    # the tag must be evidenced, not asserted
    assert "Quote or cite" in RUBRIC


def test_tier_is_derived_from_the_flag_list():
    """The tier used to be a second, independent judgement, which is how
    'CLEAN with 1 cyclical red flag' — self-contradictory under the tier
    definitions — became a verdict."""
    # whitespace-normalized: the prompt wraps, and a line break inside a
    # phrase is not a change in meaning
    assessment = re.sub(r"\s+", " ", PROMPT.split("## Assessment")[1])

    assert "DERIVED from the flag list" in assessment
    assert "CLEAN — zero red flags" in assessment
    assert "MIXED — one or more red flags" in assessment
    # and the specific contradiction is named so it cannot be re-derived
    assert '"CLEAN with one red flag" is not a valid verdict' in assessment


def test_verdict_line_has_one_fixed_machine_readable_form():
    """The same verdict rendered three ways across runs, so it could not be
    compared or parsed."""
    summary = PROMPT.split("## Executive Summary")[1].split("## 1.")[0]

    assert "**Assessment: <TIER>, <N> red flag(s)**" in summary
    assert "**Assessment: INSUFFICIENT_EVIDENCE**" in summary
    assert "exactly CLEAN, MIXED, or IMPAIRED" in summary


def test_coverage_gate_still_precedes_the_tier():
    """The rubric must not have displaced the evidentiary gate — a run that
    saw too little should still refuse a tier rather than grade what it has."""
    assessment = PROMPT.split("## Assessment")[1]

    gate = assessment.index("Evidentiary coverage gate")
    tier = assessment.index("Earnings quality tier")
    assert gate < tier
    assert "Never assign a tier when the coverage gate above says not to." in assessment
