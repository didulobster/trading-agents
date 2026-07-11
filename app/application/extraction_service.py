from typing import Literal
from pydantic import BaseModel

from app.infrastructure.repositories.chunk_repo import RetrievedChunk


class FinancialMetrics(BaseModel):
    revenue: float | None
    gross_margin_pct: float | None
    gaap_net_income: float | None
    free_cash_flow: float | None
    sbc_pct_of_revenue: float | None
    net_dollar_retention: float | None
    extraction_confidence: Literal["stated", "computed", "not_disclosed"]
    reasoning: str  # forces the model to show its work — cheap sanity check

class MetricsExtractor:
    async def extract(
        self, 
        chunks: list[RetrievedChunk], 
        ticker: str, 
        period: str) -> FinancialMetrics:
        context = "\n\n".join(f"[{c.chunk.section_path}]\n{c.chunk.content}" for c in chunks)
        response = await self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            tools=[{
                "name": "record_metrics",
                "input_schema": FinancialMetrics.model_json_schema(),
            }],
            tool_choice={"type": "tool", "name": "record_metrics"},
            messages=[{
                "role": "user",
                "content": f"""Extract financial metrics for {ticker} {period} from these filing excerpts.
                
                Rules:
                - If a number is stated directly, confidence = "stated"
                - If you must combine two disclosed numbers to compute it (e.g. margin from revenue and cost), confidence = "computed" and show the calculation in reasoning
                - If not present in the excerpts, return null and confidence = "not_disclosed" — never estimate from general knowledge
                - Never mix time periods when computing a metric

                Excerpts:
                {context}"""
                            }])
        tool_call = next(b for b in response.content if b.type == "tool_use")
        return FinancialMetrics.model_validate(tool_call.input)