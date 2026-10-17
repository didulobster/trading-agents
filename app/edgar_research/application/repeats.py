"""Collapse a footnote repeated across filings down to its newest copy."""

import re

from app.edgar_research.infrastructure.repositories.chunk_repo import RetrievedChunk

# Chosen on the 49-question gold set: 0.6 moved acn-debt-use-of-proceeds from
# rank 9 to 1 and changed no other question for the worse; 0.8 collapsed too
# little to reach it. See docs/retrieval-decision-log.md (D15).
REPEAT_THRESHOLD = 0.6


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9.,%$]*", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def collapse_repeats(
    results: list[RetrievedChunk], threshold: float = REPEAT_THRESHOLD
) -> list[RetrievedChunk]:
    """Keep one copy of text that several filings repeat: the newest, in the best slot.

    Companies restate the same note in every 10-Q and 10-K, so an old copy can
    outrank the one current filing that changed it. Walking in rank order, a
    chunk nearly identical to one already kept, but from another filing, is a
    repeat: if newer, it takes the kept chunk's slot; if older, it is dropped.
    """
    kept: list[RetrievedChunk] = []
    word_sets: list[set[str]] = []
    for result in results:
        words = _words(result.chunk.content)
        for i, other in enumerate(kept):
            if _same_filing(result, other) or _jaccard(words, word_sets[i]) < threshold:
                continue
            if result.chunk.filed_date > other.chunk.filed_date:
                kept[i], word_sets[i] = result, words
            break
        else:
            kept.append(result)
            word_sets.append(words)
    return kept


def _same_filing(a: RetrievedChunk, b: RetrievedChunk) -> bool:
    return (a.chunk.filing_type, a.chunk.filed_date) == (b.chunk.filing_type, b.chunk.filed_date)
