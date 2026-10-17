"""Add the words filers use to the words analysts use, for keyword search.

Keyword search matches stems, so "contingent liabilities" finds nothing in a
note titled "Commitments and Contingencies", and "buybacks" misses
"repurchases of common stock". On the retrieval gold set the Broadcom
contingencies note ranked 50th by keyword and ASML's customer-concentration
passages 38th.

The phrases are general SEC vocabulary, not lifted from any one filing. The
keyword query ORs its terms, so an added phrase can widen the match but never
removes one. The vector side is left alone.
"""

import re

_FILER_TERMS: dict[str, str] = {
    r"supply\s+chains?": "suppliers third-party manufacturers vendors sourcing",
    r"contingent\s+liabilit(?:y|ies)": "commitments and contingencies legal proceedings guarantees",
    r"buy[\s-]?backs?": "share repurchases repurchases of common stock purchases of shares",
    r"customer\s+concentration": "largest customers significant customers percentage of net revenue",
    r"capital\s+intensity": "capital expenditures purchases of property and equipment",
    r"EBITDA": "operating income depreciation and amortization",
    r"pricing\s+power": "average selling prices pricing pressure",
    r"moat": "competitive position competition",
}

_PATTERNS = [(re.compile(rf"\b{p}\b", re.IGNORECASE), terms) for p, terms in _FILER_TERMS.items()]


def with_filer_terms(question: str) -> str:
    """`question` with filer vocabulary appended for each analyst term it uses."""
    extra = [terms for pattern, terms in _PATTERNS if pattern.search(question)]
    return " ".join([question, *extra])
