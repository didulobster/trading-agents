from dataclasses import dataclass
from datetime import date, datetime
import json
from typing import Literal
from app.application.extraction_service import FinancialMetrics
from sqlalchemy.dialects.postgresql import insert

from app.infrastructure.repositories.db import get_connection

@dataclass(frozen=True)
class FinancialMetrics:
    """Extracted financial metrics for one ticker/period."""
    ticker: str
    fiscal_period: str                          # "Q1 2026"
    filing_type: str                            # "10-Q", "10-K"
    filed_date: date
    revenue: float | None                       # $M
    gross_margin_pct: float | None              # e.g. 79.0
    gaap_net_income: float | None               # $M
    free_cash_flow: float | None                # $M
    sbc_pct_of_revenue: float | None            # e.g. 50.7
    net_dollar_retention: float | None          # e.g. 139.0
    extraction_confidence: Literal["stated", "computed", "not_disclosed"]
    reasoning: str                              # model shows its work
    source_citations: list[str]
    extracted_at: datetime | None = None

class MetricsRepository:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def upsert(self, metrics: FinancialMetrics) -> None:
        """
        Insert or update one metrics row.
        ON CONFLICT on (ticker, filing_type, fiscal_period) — re-running
        extraction on the same filing refreshes the row, never duplicates.
        """
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO financial_metrics (
                        ticker, fiscal_period, filing_type, filed_date,
                        revenue, gross_margin_pct, gaap_net_income,
                        free_cash_flow, sbc_pct_of_revenue, net_dollar_retention,
                        extraction_confidence, source_citations
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s
                    )
                    ON CONFLICT ON CONSTRAINT uq_metric_period DO UPDATE SET
                        revenue                = EXCLUDED.revenue,
                        gross_margin_pct       = EXCLUDED.gross_margin_pct,
                        gaap_net_income        = EXCLUDED.gaap_net_income,
                        free_cash_flow         = EXCLUDED.free_cash_flow,
                        sbc_pct_of_revenue     = EXCLUDED.sbc_pct_of_revenue,
                        net_dollar_retention   = EXCLUDED.net_dollar_retention,
                        extraction_confidence  = EXCLUDED.extraction_confidence,
                        source_citations       = EXCLUDED.source_citations,
                        extracted_at           = now()
                    """,
                    (
                        metrics.ticker.upper(),
                        metrics.fiscal_period,
                        metrics.filing_type,
                        metrics.filed_date,
                        metrics.revenue,
                        metrics.gross_margin_pct,
                        metrics.gaap_net_income,
                        metrics.free_cash_flow,
                        metrics.sbc_pct_of_revenue,
                        metrics.net_dollar_retention,
                        metrics.extraction_confidence,
                        json.dumps(metrics.source_citations),
                    ),
                )
                await conn.commit()

    async def get(self, ticker: str, fiscal_period: str) -> FinancialMetrics | None:
        """Fetch one row by ticker + period. Returns None if not yet extracted."""
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        ticker, fiscal_period, filing_type, filed_date,
                        revenue, gross_margin_pct, gaap_net_income,
                        free_cash_flow, sbc_pct_of_revenue, net_dollar_retention,
                        extraction_confidence, reasoning, source_citations, extracted_at
                    FROM financial_metrics
                    WHERE ticker = %s AND fiscal_period = %s
                    """,
                    (ticker.upper(), fiscal_period),
                )
                row = await cur.fetchone()

        if row is None:
            return None
        return self._row_to_metrics(row)

    async def list_by_ticker(self, ticker: str) -> list[FinancialMetrics]:
        """All periods for one ticker, oldest first — this is your trend query."""
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        ticker, fiscal_period, filing_type, filed_date,
                        revenue, gross_margin_pct, gaap_net_income,
                        free_cash_flow, sbc_pct_of_revenue, net_dollar_retention,
                        extraction_confidence, reasoning, source_citations, extracted_at
                    FROM financial_metrics
                    WHERE ticker = %s
                    ORDER BY filed_date ASC
                    """,
                    (ticker.upper(),),
                )
                rows = await cur.fetchall()

        return [self._row_to_metrics(r) for r in rows]

    async def list_by_tickers(self, tickers: list[str]) -> list[FinancialMetrics]:
        """
        Cross-ticker comparison — same columns, multiple tickers.
        e.g. FIG vs ADBE gross_margin_pct side by side.
        """
        async with get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT
                        ticker, fiscal_period, filing_type, filed_date,
                        revenue, gross_margin_pct, gaap_net_income,
                        free_cash_flow, sbc_pct_of_revenue, net_dollar_retention,
                        extraction_confidence, reasoning, source_citations, extracted_at
                    FROM financial_metrics
                    WHERE ticker = ANY(%s)
                    ORDER BY ticker ASC, filed_date ASC
                    """,
                    ([t.upper() for t in tickers],),
                )
                rows = await cur.fetchall()

        return [self._row_to_metrics(r) for r in rows]

    @staticmethod
    def _row_to_metrics(row: dict) -> FinancialMetrics:
        """Shared row → dataclass conversion. Mirror of Chunk.model_validate pattern."""
        return FinancialMetrics(
            ticker=row["ticker"],
            fiscal_period=row["fiscal_period"],
            filing_type=row["filing_type"],
            filed_date=row["filed_date"],
            revenue=row["revenue"],
            gross_margin_pct=row["gross_margin_pct"],
            gaap_net_income=row["gaap_net_income"],
            free_cash_flow=row["free_cash_flow"],
            sbc_pct_of_revenue=row["sbc_pct_of_revenue"],
            net_dollar_retention=row["net_dollar_retention"],
            extraction_confidence=row["extraction_confidence"],
            reasoning=row["reasoning"],
            source_citations=json.loads(row["source_citations"]) if isinstance(row["source_citations"], str) else row["source_citations"],
            extracted_at=row["extracted_at"],
        )