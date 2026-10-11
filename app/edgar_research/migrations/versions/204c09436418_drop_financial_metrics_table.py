"""drop financial_metrics table

Written by POST /extract and the extract-metrics CLI, read by nothing: the
repository's only read method had no caller, and the trend queries the
table was built for never existed. /extract still returns the metrics; it
no longer stores them.

The downgrade recreates the table as d8cd6a0f2f2f and 9f2a7c1d4e83 left it,
empty. Rows dropped by the upgrade are not recoverable.

Revision ID: 204c09436418
Revises: 9f2a7c1d4e83
Create Date: 2026-10-11 21:09:26.783786

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '204c09436418'
down_revision: Union[str, Sequence[str], None] = '9f2a7c1d4e83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("financial_metrics")


def downgrade() -> None:
    op.create_table(
        "financial_metrics",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ticker", sa.String, nullable=False),
        sa.Column("filing_type", sa.String, nullable=False),
        sa.Column("fiscal_period", sa.String, nullable=False),
        sa.Column("filed_date", sa.Date, nullable=False),
        sa.Column("revenue", sa.Numeric, nullable=True),
        sa.Column("gross_margin_pct", sa.Numeric, nullable=True),
        sa.Column("gaap_net_income", sa.Numeric, nullable=True),
        sa.Column("free_cash_flow", sa.Numeric, nullable=True),
        sa.Column("sbc_pct_of_revenue", sa.Numeric, nullable=True),
        sa.Column("net_dollar_retention", sa.Numeric, nullable=True),
        sa.Column("extraction_confidence", sa.String, nullable=False),
        sa.Column("source_citations", postgresql.JSONB, nullable=False),
        sa.Column("extracted_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("reasoning", sa.Text, nullable=True, server_default=""),
        sa.UniqueConstraint("ticker", "filing_type", "fiscal_period", name="uq_metric_period"),
    )
