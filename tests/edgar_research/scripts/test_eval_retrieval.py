"""The retrieval eval's scoring: answers are matched by text, never by chunk id."""

from app.edgar_research.scripts.eval_retrieval import (
    GoldQuestion,
    first_hit_rank,
    load_gold,
    normalize,
    summarize,
)


def _gold(answers: list[str], require: str = "any") -> GoldQuestion:
    return GoldQuestion(
        id="q", tag="narrative", ticker="ACN", question="?", answers=answers, require=require
    )


def test_normalize_folds_curly_quotes_case_and_whitespace():
    assert normalize("We  have served as the Company’s\nAuditor") == "we have served as the company's auditor"


def test_any_returns_the_rank_of_the_first_chunk_holding_an_answer():
    chunks = ["nothing here", "revenue was 74,183", "also 69,673"]
    assert first_hit_rank(chunks, _gold(["69,673", "74,183"])) == 2


def test_all_needs_every_answer_across_the_prefix():
    chunks = ["revenue was 74,183", "filler", "prior year 69,673"]
    assert first_hit_rank(chunks, _gold(["74,183", "69,673"], require="all")) == 3


def test_a_missing_answer_is_not_a_hit():
    assert first_hit_rank(["74,183 only"], _gold(["74,183", "69,673"], require="all")) is None
    assert first_hit_rank([], _gold(["74,183"])) is None


def test_summarize_reports_hit_at_k_and_mrr():
    s = summarize([1, 5, 9, None])
    assert s["hit@1"] == 0.25
    assert s["hit@5"] == 0.5
    assert s["hit@8"] == 0.5
    assert round(s["mrr"], 4) == round((1 + 1 / 5 + 1 / 9) / 4, 4)


def test_the_committed_gold_set_loads_with_unique_ids_and_known_tags():
    golds = load_gold()
    assert len({g.id for g in golds}) == len(golds)
    assert {g.tag for g in golds} <= {
        "numeric_table", "numeric_prose", "narrative", "vocab_mismatch", "multi_part", "8k_by_date",
        "instructed",
    }
    assert all(g.answers and g.require in ("any", "all") for g in golds)
