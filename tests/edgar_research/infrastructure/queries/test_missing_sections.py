"""`corpus-status` flags embedded 10-Ks/10-Qs with no MD&A or financial
statements section. ACN's March and June 2026 10-Qs were embedded as one
['Unknown', 'Full Document'] section and looked normal by chunk count."""

from app.edgar_research.infrastructure.queries.corpus_status import missing_sections

TEN_Q = {("Part I", "Item 1"), ("Part I", "Item 2"), ("Part II", "Item 1A")}


def test_complete_10q_and_10k_pass():
    assert missing_sections("10-Q", TEN_Q) == []
    assert missing_sections("10-K", {("Part II", "Item 7"), ("Part II", "Item 8")}) == []


def test_full_document_fallback_misses_both():
    assert missing_sections("10-Q", {("Unknown", "Full Document")}) == [
        "Part I Item 1", "Part I Item 2",
    ]


def test_part_ii_item_1_does_not_stand_in_for_the_financial_statements():
    """10-Q Part II Item 1 is Legal Proceedings, not Part I's statements."""
    assert missing_sections("10-Q", {("Part II", "Item 1"), ("Part I", "Item 2")}) == [
        "Part I Item 1",
    ]


def test_10k_missing_mdna():
    assert missing_sections("10-K", {("Part II", "Item 8")}) == ["Part II Item 7"]


def test_other_forms_are_not_checked():
    assert missing_sections("8-K", set()) == []
