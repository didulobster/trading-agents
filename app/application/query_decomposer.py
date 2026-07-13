from dataclasses import dataclass
import logging
import os
import re
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

# Stage 1: keyword signals that a query needs LLM rewriting.
# Two categories now: multi-fact signals AND vocabulary-mismatch signals.
_NEEDS_REWRITE_SIGNALS = re.compile(
    r"""
    # Multi-fact / synthesis signals (existing)
    \b(vs\.?|versus|relative\s+to|compar(e|ed|ing)\b|
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

# Vocabulary-mismatch signals: analyst jargon that filers phrase differently.
# These are terms your eval has confirmed don't appear verbatim in filings.
_VOCABULARY_MISMATCH_TERMS = re.compile(
    r"""
    \b(supply\s+chain|
    contingent\s+liabilit|
    capital\s+intensity|
    buyback|
    EBITDA|
    customer\s+concentration|
    moat|
    switching\s+cost|
    pricing\s+power)
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

REWRITE_PROMPT = """You are a financial research query rewriter. Your job is to take an investment research question and produce 2-4 alternative phrasings that are more likely to match the language used in SEC 10-K filings.

SEC filings use formal accounting and legal terminology, not analyst jargon. Common translations:
- "supply chain risks" → "third-party vendor dependencies", "outsourcing partners", "manufacturing concentration"
- "contingent liabilities" → "commitments and contingencies", "legal proceedings", "loss contingencies"
- "buybacks" → "share repurchase program", "repurchases of common stock"
- "capital intensity" → "capital expenditures as percentage of revenue", "property plant and equipment additions"
- "customer concentration" → "significant customers", "concentration of credit risk"
- "EBITDA" → "operating profit", "operating income", "profit before taxes"

Rules:
- Each variant should use vocabulary that actually appears in SEC filings
- Keep the company name and temporal scope from the original query
- Each variant should approach the concept from a DIFFERENT angle, not just swap one synonym
- If the query asks about multiple distinct facts, split into independent sub-queries (one fact each)
- Return ONLY the rewritten queries, one per line, no numbering, no explanation
- Include the original query as the FIRST line (it may still match some filings)

Original query: "{question}"
Rewritten queries:"""

@dataclass(frozen=True)
class DecompositionResult:
    """Result of query decomposition."""
    original_query: str
    was_decomposed: bool
    sub_queries: list[str]   # if not decomposed, contains [original_query]

class QueryDecomposer:
    """
    Two-stage query rewriting:
    1. Cheap regex detection — does the query contain multi-fact signals
       OR vocabulary-mismatch terms?
    2. LLM rewriting — decompose into sub-queries OR expand into
       filer-vocabulary variants.

    The LLM decides whether to split or expand based on the query structure.
    Simple factual queries using standard filing terminology bypass both stages.
    """

    def __init__(self, model: str | None = None):
        self._client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self._model = model or os.getenv("LLM_CLAUDE_MODEL")

    def needs_rewrite(self, query: str) -> str | None:
        """Stage 1: cheap detection.
            Returns 'decompose', 'expand', or None.
        """
        if _NEEDS_REWRITE_SIGNALS.search(query):
            return "decompose"
        if _VOCABULARY_MISMATCH_TERMS.search(query):
            return "expand"
        return None

    async def decompose(self, query: str) -> DecompositionResult:
        """
        Full pipeline: detect, then rewrite if needed.
        Returns the original query unchanged if no rewrite is needed.
        """
        rewrite_type = self.needs_rewrite(query);
        if rewrite_type is None:
            logger.debug("Query does not need rewriting: %s", query[:80])
            return DecompositionResult(
                original_query=query,
                was_decomposed=False,
                sub_queries=[query],
            )

        if rewrite_type == "decompose":
            logger.info("Rewriting decompose query: %s", query[:80])
            prompt = DECOMPOSITION_PROMPT.format(question=query)
        else:
            logger.info("Rewriting expansion query: %s", query[:80])
            prompt = REWRITE_PROMPT.format(question=query)

        resp = await self._client.messages.create( 
            model=self._model,
            max_tokens=512,
            temperature=0,
            messages=[{
                "role": "user",
                "content": prompt,
            }],
        )
        raw = resp.content[0].text.strip()
        sub_queries = [
            line.strip()
            for line in raw.splitlines()
            if line.strip()
            and not line.strip().lower().startswith("rewritten")
            and not line.strip().lower().startswith("original")
        ]

        if not sub_queries:
            logger.warning("Rewriting returned no variants; falling back to original")
            return DecompositionResult(
                original_query=query,
                was_decomposed=False,
                sub_queries=[query],
            )

        logger.info("Rewrote into %d sub-queries: %s", len(sub_queries), sub_queries)
        return DecompositionResult(
            original_query=query,
            was_decomposed=True,
            sub_queries=sub_queries,
        ) 