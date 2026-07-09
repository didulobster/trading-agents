"""add tsvector column for bm25 search

Revision ID: 25b4b18dcb28
Revises: e420dedd72c0
Create Date: 2026-07-08 07:36:48.963552

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25b4b18dcb28'
down_revision: Union[str, Sequence[str], None] = 'e420dedd72c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add tsvector column
    op.execute("""
        ALTER TABLE chunks
        ADD COLUMN content_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
    """)
    # GIN index for full-text search
    op.execute("""
        CREATE INDEX ix_chunks_content_tsv
        ON chunks USING gin (content_tsv)
    """)

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunks_content_tsv")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS content_tsv")

