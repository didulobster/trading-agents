from datetime import date, datetime
from pydantic import BaseModel

from .values import SectionPath, Ticker
from app.edgar_research.infrastructure.chunking.models import ChunkDraft


class Chunk(BaseModel):
    """A retrievable, embeddable piece of a section."""
    id: int | None = None
    section_id: int
    content: str
    chunk_index: int
    token_count: int
    embedding: list[float] | None = None    # None until embedded

    # Denormalized for fast metadata-filtered retrieval
    ticker: Ticker
    filed_date: date
    filing_type: str
    section_path: SectionPath

    created_at: datetime | None = None

    def embedding_text(self) -> str:
        """What gets embedded: the content under a line naming its filing and section.

        A chunk cut from the middle of a statement table ("Cash and cash
        equivalents | 11,478,729 | ...") carries no company, form, date or
        section of its own, so its vector sat far from a question that names
        them. Only the vector sees this line; `content` (what is cited,
        verified and keyword-searched) is unchanged.
        """
        section = " > ".join(self.section_path)
        return f"{self.ticker} {self.filing_type} filed {self.filed_date.isoformat()} | {section}\n\n{self.content}"

def chunk_from_draft(
    draft: ChunkDraft,
    section_id: int,
    ticker: str,
    filed_date: date,
    filing_type: str,
) -> Chunk:
    """Lift a chunker output into a persistable domain Chunk."""
    return Chunk(
        section_id=section_id,
        content=draft.content,
        chunk_index=draft.chunk_index,
        token_count=draft.token_count,
        ticker=ticker,
        filed_date=filed_date,
        filing_type=filing_type,
        section_path=draft.section_path,
    )