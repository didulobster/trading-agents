# EDGAR Research

Ingests SEC EDGAR filings into a searchable corpus and answers questions over it, from a single grounded answer up to a full fundamentals memo written by the Research agent.

## Language

**Corpus**:
The filings ingested so far, broken into sections and chunks and embedded for retrieval. A cache, not a precondition: the Research agent ingests a missing filing on demand.
_Avoid_: index, knowledge base, vector store

**Research agent**:
The tool-using model that asks the corpus questions and computes from what it gets back, ending in a fundamentals memo.
_Avoid_: researcher, agent, analyst

**Fundamentals memo**:
The Research agent's written assessment of one ticker, ending in an earnings quality tier (CLEAN, MIXED or IMPAIRED) or INSUFFICIENT_EVIDENCE when coverage is too thin.
_Avoid_: memo, report, research report

**News assessment**:
The Research agent's judgment of one headline about a ticker, checked against that ticker's filings.
_Avoid_: news digest, news analysis
