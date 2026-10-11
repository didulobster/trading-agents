"""How several rankings become one.

`retrieve_full` fused sub-query results by taking each chunk's MAX score
across sub-queries. RRF scores are rank-derived, so that means "the best
rank this chunk reached in any sub-query" — a chunk every sub-query ranked
third scored exactly the same as one a single sub-query ranked third and
the rest missed. Agreement across sub-queries is the reason to decompose a
question at all, and the max discarded it.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.edgar_research.application.retrieval_service import RetrievalService, _fuse_across_queries
from app.edgar_research.domain.chunk import Chunk
from app.edgar_research.infrastructure.repositories.chunk_repo import RetrievedChunk


def _rc(cid: int, sim: float, vec: float | None = None) -> RetrievedChunk:
    chunk = Chunk(
        id=cid, section_id=1, content="x", chunk_index=cid, token_count=1,
        ticker="ACN", filed_date=date(2025, 10, 10), filing_type="10-K",
        section_path=["Part II", "Item 7"],
    )
    return RetrievedChunk(chunk=chunk, similarity=sim, vector_similarity=vec)


# ---------------------------------------------------------------------------
# Fusion across sub-queries
# ---------------------------------------------------------------------------

def test_a_chunk_two_sub_queries_agree_on_outranks_one_only_a_single_query_found():
    fused = _fuse_across_queries([[_rc(1, 0.030)], [_rc(2, 0.020)], [_rc(2, 0.025)]], k=8)
    assert [(c.chunk.id, round(c.similarity, 6)) for c in fused] == [(2, 0.045), (1, 0.03)]


def test_the_max_merge_would_have_ranked_them_the_other_way():
    """The behaviour being replaced, stated so the change is not silent."""
    per_query = [[_rc(1, 0.030)], [_rc(2, 0.020)], [_rc(2, 0.025)]]
    by_max = sorted(
        {c.chunk.id: c.similarity for q in per_query for c in q}.items(),
        key=lambda kv: kv[1], reverse=True,
    )
    assert by_max[0][0] == 1                       # old: the single-query chunk won
    assert _fuse_across_queries(per_query, k=8)[0].chunk.id == 2   # new: agreement wins


def test_a_chunk_found_once_still_participates():
    fused = _fuse_across_queries([[_rc(1, 0.03)], [_rc(9, 0.001)]], k=8)
    assert {c.chunk.id for c in fused} == {1, 9}


def test_fusion_truncates_to_k():
    fused = _fuse_across_queries([[_rc(i, 1.0 / i) for i in range(1, 20)]], k=5)
    assert len(fused) == 5
    assert [c.chunk.id for c in fused] == [1, 2, 3, 4, 5]


def test_the_cosine_similarity_carried_through_is_the_best_one_the_chunk_got():
    """`similarity` becomes the fused score; vector_similarity must stay a
    real cosine number, because that is what ask_edgar shows the agent."""
    fused = _fuse_across_queries([[_rc(1, 0.01, vec=0.55)], [_rc(1, 0.03, vec=0.71)]], k=8)
    assert fused[0].similarity == pytest.approx(0.04)
    assert fused[0].vector_similarity == 0.71


def test_no_results_fuse_to_nothing():
    assert _fuse_across_queries([[], []], k=8) == []


# ---------------------------------------------------------------------------
# The dead knob, and the dead method
# ---------------------------------------------------------------------------

def test_the_service_no_longer_takes_a_switch_it_never_read():
    with pytest.raises(TypeError):
        RetrievalService(embedding_service=None, chunk_repo=None, use_hybrid=True)


def test_the_vector_only_decomposition_path_is_gone():
    """Its only caller was the eval harness, measuring a path /ask does not
    take. Keeping it would keep that measurement available."""
    assert not hasattr(RetrievalService, "retrieve_with_decomposition")

