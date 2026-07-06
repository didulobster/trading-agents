from dataclasses import dataclass
import logging
import os
import re
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

# Keyword signals that a query likely needs multiple distinct facts.
# Deliberately conservative — false negatives (missed decomposition)
# are preferable to false positives (unnecessary LLM calls on simple queries).
_MULTI_FACT_SIGNALS = re.compile(
    r"""
    \b(vs\.?|versus|relative\s+to|compared\s+(to|with)|
    as\s+a?\s*%\s*of|as\s+percentage\s+of|
    faster\s+than|slower\s+than|
    comes?\s+from.*\bvs\b|
    trajectory|trend|
    ratio\s+of|
    growing.*(faster|slower)|
    buyback.*operational|operational.*buyback)
    """,
    re.IGNORECASE | re.VERBOSE,
)

DECOMPOSITION_PROMPT = """You are a financial research query decomposer. Given a complex investment research question that requires multiple distinct facts to answer, break it into independent sub-queries that can each be answered by searching a corpus of SEC 10-K filings.

Rules:
- Each sub-query should target ONE specific fact or data point
- Use the vocabulary that SEC filings actually use (e.g., "net income" not "earnings", "share repurchase" not "buyback", "operating profit" not "operational improvement")
- Include the company name in each sub-query
- Include temporal scope if the original question implies it
- Return 2-4 sub-queries, no more
- Return ONLY the sub-queries, one per line, no numbering, no explanation

Example:
Question: "How much of Apple's earnings growth comes from buybacks vs actual operational improvement?"
Sub-queries:
Apple diluted earnings per share fiscal 2024 and 2023
Apple net income fiscal 2024 and 2023
Apple share repurchase program amounts fiscal 2024 and 2023
Apple weighted-average diluted shares outstanding fiscal 2024 and 2023

Question: "{question}"
Sub-queries:"""

@dataclass(frozen=True)
class DecompositionResult:
    """Result of query decomposition."""
    original_query: str
    was_decomposed: bool
    sub_queries: list[str]   # if not decomposed, contains [original_query]

class QueryDecomposer:
    """
    Two-stage query decomposition:
    1. Cheap keyword detection — does the query look like it needs multiple facts?
    2. LLM decomposition — split into independent sub-queries using filer vocabulary.

    Simple factual queries bypass both stages entirely.
    """

    def __init__(self, model: str | None = None):
        self._client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self._model = model or os.getenv("LLM_CLAUDE_MODEL")

    def needs_decomposition(self, query: str) -> bool:
        """Stage 1: cheap keyword check."""
        return bool(_MULTI_FACT_SIGNALS.search(query))

    async def decompose(self, query: str) -> DecompositionResult:
        """
        Full pipeline: detect, then decompose if needed.
        Returns the original query wrapped in a DecompositionResult
        if no decomposition is needed.
        """
        if not self.needs_decomposition(query):
            logger.debug("Query does not need decomposition: %s", query[:80])
            return DecompositionResult(
                original_query=query,
                was_decomposed=False,
                sub_queries=[query],
            )
        logger.info("Decomposing query: %s", query[:80])
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": DECOMPOSITION_PROMPT.format(question=query),
            }],
        )
        raw = resp.content[0].text.strip()
        sub_queries = [
            line.strip()
            for line in raw.splitlines()
            if line.strip() and not line.strip().startswith("Sub-queries")
        ]

        if not sub_queries:
            logger.warning("Decomposition returned no sub-queries; falling back to original")
            return DecompositionResult(
                original_query=query,
                was_decomposed=False,
                sub_queries=[query],
            )

        logger.info("Decomposed into %d sub-queries: %s", len(sub_queries), sub_queries)
        return DecompositionResult(
            original_query=query,
            was_decomposed=True,
            sub_queries=sub_queries,
        )