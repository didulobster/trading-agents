"""`corpus-status` flags embedded 10-Ks/10-Qs whose MD&A, risk factors or
financial statements are missing or nearly empty. ACN's March and June 2026
10-Qs were embedded as one ['Unknown', 'Full Document'] section, and MCD's
and IBM's 10-Ks parse into Items of under 200 characters; all looked normal
by chunk count."""

from app.edgar_research.infrastructure.queries.corpus_status import missing_sections

FULL = 40_000
TEN_Q = {("Part I", "Item 1"): FULL, ("Part I", "Item 2"): FULL, ("Part II", "Item 1A"): 300}
TEN_K = {("Part I", "Item 1A"): FULL, ("Part II", "Item 7"): FULL, ("Part II", "Item 8"): FULL}


def test_complete_10q_and_10k_pass():
    assert missing_sections("10-Q", TEN_Q) == []
    assert missing_sections("10-K", TEN_K) == []


def test_full_document_fallback_misses_both():
    assert missing_sections("10-Q", {("Unknown", "Full Document"): FULL}) == [
        "Part I Item 1", "Part I Item 2",
    ]


def test_part_ii_item_1_does_not_stand_in_for_the_financial_statements():
    """10-Q Part II Item 1 is Legal Proceedings, not Part I's statements."""
    assert missing_sections("10-Q", {("Part II", "Item 1"): FULL, ("Part I", "Item 2"): FULL}) == [
        "Part I Item 1",
    ]


def test_10k_missing_mdna():
    no_7 = {k: v for k, v in TEN_K.items() if k != ("Part II", "Item 7")}
    assert missing_sections("10-K", no_7) == ["Part II Item 7"]


def test_10k_missing_risk_factors():
    no_1a = {k: v for k, v in TEN_K.items() if k != ("Part I", "Item 1A")}
    assert missing_sections("10-K", no_1a) == ["Part I Item 1A"]


def test_incorporated_by_reference_items_are_tiny():
    """IBM's 2025 10-K: Items 7 and 8 point to an Annual Report exhibit."""
    ibm = {**TEN_K, ("Part II", "Item 7"): 116, ("Part II", "Item 8"): 196}
    assert missing_sections("10-K", ibm) == [
        "Part II Item 7 (116 chars)", "Part II Item 8 (196 chars)",
    ]


def test_other_forms_are_not_checked():
    assert missing_sections("8-K", {}) == []
