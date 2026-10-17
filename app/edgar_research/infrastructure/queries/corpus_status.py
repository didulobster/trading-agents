import re
from datetime import date

from app.edgar_research.infrastructure.queries.models import (
    CorpusSummaryRow, FilingDetail, FilingIssue, IncompleteFiling,
)
from app.edgar_research.infrastructure.repositories.db import get_connection

_ITEM_LABEL = re.compile(r"^Item (\d{1,2})([A-Z]?)$")

# The sections a memo is built from: risk factors, MD&A and the statements.
REQUIRED_SECTIONS = {
    "10-K": (("Part I", "Item 1A"), ("Part II", "Item 7"), ("Part II", "Item 8")),
    "10-Q": (("Part I", "Item 1"), ("Part I", "Item 2")),
}

# Healthy ACN/AVGO required Items hold 23k+ characters; MCD's and IBM's
# 2025 10-Ks parse into required Items of under 200.
MIN_SECTION_CHARS = 5_000


def missing_sections(filing_type: str, item_chars: dict[tuple[str, str], int]) -> list[str]:
    """Required (Part, Item) pairs a periodic filing lacks or has nearly empty.

    `item_chars` maps (Part, Item) to the summed length of its sections.

    A filing can reach EMBEDDED with its whole text in one
    ['Unknown', 'Full Document'] section — the parser's fallback when the
    Item split looks unreliable — and chunk counts look normal. ACN's
    March and June 2026 10-Qs sat in the corpus that way unnoticed. An Item
    can also exist but hold only a heading: MCD's 10-K splits on its table
    of contents, and IBM's incorporates Items 7 and 8 by reference.
    """
    out = []
    for part, item in REQUIRED_SECTIONS.get(filing_type, ()):
        chars = item_chars.get((part, item))
        if chars is None:
            out.append(f"{part} {item}")
        elif chars < MIN_SECTION_CHARS:
            out.append(f"{part} {item} ({chars:,} chars)")
    return out


def _item_sort_key(label: str) -> tuple[int, str]:
    """Document order: Item 2 before Item 10, Item 1 before Item 1A."""
    m = _ITEM_LABEL.match(label)
    return (int(m.group(1)), m.group(2)) if m else (99, label)


def _scope(
    ticker: str | None, filed_before: "date | None", trailing: str = ""
) -> tuple[str, tuple]:
    """The WHERE clause and params shared by every method here.

    `trailing` is "AND" for the one caller that appends its own conditions.
    """
    clauses: list[str] = []
    params: list = []
    if ticker:
        clauses.append("s.ticker = %s")
        params.append(ticker.upper())
    if filed_before:
        clauses.append("f.filed_date <= %s")
        params.append(filed_before)
    if not clauses:
        return ("WHERE" if trailing else ""), ()
    return "WHERE " + " AND ".join(clauses) + (f" {trailing}" if trailing else ""), tuple(params)


class CorpusStatusQuery:
    """Read-side query for corpus introspection. Not a repository.

    `filed_before` bounds every method at the run's analysis date. Without
    it, a historical run could not READ a later filing (ask_edgar and
    latest-filings are bounded) but could still SEE that it exists — and a
    live FIG run at --as-of 2026-03-01 did exactly that, writing into its
    memo: "The corpus also contains filings dated after the analysis
    cutoff, including Form 10-Q filed 2026-05-14 and Form 10-Q filed
    2026-08-05". Knowing a filing exists, and when, is itself information
    from after the cutoff — the same reason /latest-filings takes the bound.
    """

    async def summary(self, ticker: str | None = None, filed_before: date | None = None) -> list[CorpusSummaryRow]:
        where_clause, params = _scope(ticker, filed_before)

        async with get_connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT
                    s.ticker,
                    count(DISTINCT f.id) AS filings,
                    min(f.filed_date) AS earliest,
                    max(f.filed_date) AS latest,
                    count(DISTINCT f.id) FILTER (WHERE f.status = 'embedded') AS embedded,
                    count(DISTINCT f.id) FILTER (
                        WHERE f.status NOT IN ('embedded', 'failed')
                    ) AS partial,
                    count(DISTINCT f.id) FILTER (WHERE f.status = 'failed') AS failed,
                    count(c.id) AS chunks,
                    count(c.id) FILTER (WHERE c.embedding IS NOT NULL) AS embedded_chunks
                FROM listed_securities s
                LEFT JOIN filings f ON f.security_id = s.id
                LEFT JOIN documents d ON d.filing_id = f.id
                LEFT JOIN sections sec ON sec.document_id = d.id
                LEFT JOIN chunks c ON c.section_id = sec.id
                {where_clause}
                GROUP BY s.ticker
                ORDER BY s.ticker
                """,
                params,
            )
            rows = await cur.fetchall()

        return [CorpusSummaryRow(**r) for r in rows]

    async def issues(self, ticker: str | None = None, filed_before: date | None = None) -> list[FilingIssue]:
        where_clause, params = _scope(ticker, filed_before, trailing="AND")

        async with get_connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT s.ticker, f.accession_number, f.filing_type,
                       f.filed_date, f.status::text AS status,
                       f.error_message, f.updated_at
                FROM filings f
                JOIN listed_securities s ON s.id = f.security_id
                {where_clause} (
                    f.status NOT IN ('embedded', 'failed')
                    OR f.status = 'failed'
                )
                ORDER BY f.updated_at
                """,
                params,
            )
            rows = await cur.fetchall()

        return [FilingIssue(**r) for r in rows]

    async def item_sections(self, ticker: str | None = None, filed_before: date | None = None) -> list[str]:
        """The Item labels `ask_edgar`'s `sections` filter will match.

        Told only that a section filter exists, the agent guesses accounting
        note titles — "Revenue Recognition", "Consolidated Statements of
        Income", "Goodwill". Measured on ACN 2026-09-12, 18 of 29 filtered
        calls named something no chunk is filed under. Nothing in a section
        path is a note title: paths look like ['Part II', 'Item 9A',
        'Controls and Procedures'].

        Item labels rather than every distinct path element, because the
        elements include long titles that differ between filings by an
        apostrophe ("Management's" vs "Management’s") and would be 49 strings
        for ACN alone. The Items are short, canonical, and cover the same
        ground — the F-pages are under Item 8 since PR #94.
        """
        # Queries `chunks` directly, which carries its own denormalized
        # ticker/filed_date — so the bound is spelled without the join alias
        # `_scope` uses.
        clauses, params_list = [], []
        if ticker:
            clauses.append("ticker = %s")
            params_list.append(ticker.upper())
        if filed_before:
            clauses.append("filed_date <= %s")
            params_list.append(filed_before)
        where_clause = ("WHERE " + " AND ".join(clauses) + " AND") if clauses else "WHERE"
        params: tuple = tuple(params_list)

        async with get_connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT DISTINCT unnest(section_path) AS part
                FROM chunks
                {where_clause} section_path IS NOT NULL
                """,
                params,
            )
            parts = [r["part"] for r in await cur.fetchall()]

        items = [p for p in parts if _ITEM_LABEL.match(p)]
        return sorted(items, key=_item_sort_key)

    async def per_filing(self, ticker: str | None = None, filed_before: date | None = None) -> list[FilingDetail]:
        where_clause, params = _scope(ticker, filed_before)

        async with get_connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT s.ticker, f.accession_number, f.filing_type,
                       f.filed_date, f.status::text AS status,
                       count(c.id) AS chunks,
                       count(c.id) FILTER (WHERE c.embedding IS NOT NULL) AS embedded
                FROM filings f
                JOIN listed_securities s ON s.id = f.security_id
                LEFT JOIN documents d ON d.filing_id = f.id
                LEFT JOIN sections sec ON sec.document_id = d.id
                LEFT JOIN chunks c ON c.section_id = sec.id
                {where_clause}
                GROUP BY s.ticker, f.accession_number, f.filing_type,
                         f.filed_date, f.status
                ORDER BY s.ticker, f.filed_date DESC
                """,
                params,
            )
            rows = await cur.fetchall()

        return [FilingDetail(**r) for r in rows]

    async def incomplete_filings(
        self, ticker: str | None = None, filed_before: date | None = None
    ) -> list[IncompleteFiling]:
        """Embedded 10-Ks and 10-Qs whose required sections are missing or tiny."""
        where_clause, params = _scope(ticker, filed_before, trailing="AND")

        async with get_connection() as conn, conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT s.ticker, f.accession_number, f.filing_type, f.filed_date,
                       sec.section_path[1] AS part, sec.section_path[2] AS item,
                       sum(length(sec.content)) AS chars
                FROM filings f
                JOIN listed_securities s ON s.id = f.security_id
                LEFT JOIN documents d ON d.filing_id = f.id
                LEFT JOIN sections sec ON sec.document_id = d.id
                {where_clause} f.status = 'embedded'
                    AND f.filing_type = ANY(%s)
                GROUP BY s.ticker, f.accession_number, f.filing_type, f.filed_date,
                         sec.section_path[1], sec.section_path[2]
                ORDER BY s.ticker, f.filed_date DESC
                """,
                params + (list(REQUIRED_SECTIONS),),
            )
            rows = await cur.fetchall()

        filings: dict[str, tuple[dict, dict[tuple[str, str], int]]] = {}
        for r in rows:
            _, item_chars = filings.setdefault(r["accession_number"], (r, {}))
            if r["part"] and r["item"]:
                item_chars[(r["part"], r["item"])] = r["chars"]

        out = []
        for r, item_chars in filings.values():
            missing = missing_sections(r["filing_type"], item_chars)
            if missing:
                out.append(IncompleteFiling(
                    ticker=r["ticker"], accession_number=r["accession_number"],
                    filing_type=r["filing_type"], filed_date=r["filed_date"],
                    missing=missing,
                ))
        return out
