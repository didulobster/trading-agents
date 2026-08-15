from datetime import date
from pydantic import BaseModel


class FundamentalsReport(BaseModel):
    ticker: str
    summary: str
    input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    generated_at: date