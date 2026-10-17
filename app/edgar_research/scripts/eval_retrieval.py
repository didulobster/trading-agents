"""Does retrieval put the answer in front of the model? Embeddings only, no LLM calls.

Replays the gold set (`retrieval_gold.yaml`) through the vector, keyword and
hybrid searches and reports, per question tag, how often and how high the
answer text ranks. A question is answered when the retrieved chunks CONTAIN
the gold answer strings; chunk ids are never compared, because they change on
every re-ingest.

Hybrid here fuses `3 * depth` candidates per path, so ranks beyond the
production k=8 can differ slightly from `retrieve_hybrid(k=8)`.

`--decompose` adds a fourth column, "decomposed": the production path
(`retrieve_full`), which rewrites a question into sub-queries first when its
wording trips the decomposer's regex. That is an LLM call per rewritten
question and one embedding per sub-query; the run prints what it spent.

Cost without `--decompose`: one embedding per question (a fraction of a cent
for the whole set).

    uv run python -m app.edgar_research.scripts.eval_retrieval [--depth 20] [--decompose]
    uv run python -m app.edgar_research.scripts.eval_retrieval --check-gold   # no API calls
"""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from app.edgar_research.application.query_decomposer import DecompositionResult
from app.shared.config import load_env

GOLD_PATH = Path(__file__).with_name("retrieval_gold.yaml")
MODES = ("vector", "keyword", "hybrid")
REPORT_KS = (1, 5, 8)


@dataclass(frozen=True)
class GoldQuestion:
    id: str
    tag: str
    ticker: str
    question: str
    answers: list[str]
    require: str = "any"
    filing_types: list[str] | None = None
    filed_after: date | None = None
    filed_before: date | None = None


def load_gold(path: Path = GOLD_PATH) -> list[GoldQuestion]:
    return [GoldQuestion(**entry) for entry in yaml.safe_load(path.read_text())]


def normalize(text: str) -> str:
    """Lowercase, fold curly quotes, collapse whitespace."""
    folded = text.replace("’", "'").replace("‘", "'").replace(" ", " ")
    return " ".join(folded.lower().split())


def first_hit_rank(contents: list[str], gold: GoldQuestion) -> int | None:
    """1-based rank at which the answer is first fully in front of the model.

    `any`: the first chunk containing any answer string. `all`: the smallest
    prefix whose chunks together contain every answer string.
    """
    wanted = [normalize(a) for a in gold.answers]
    seen = ""
    for rank, content in enumerate(contents, start=1):
        seen += " " + normalize(content)
        found = [a in seen for a in wanted]
        if all(found) if gold.require == "all" else any(found):
            return rank
    return None


def summarize(ranks: list[int | None]) -> dict[str, float]:
    """hit@k for each reported k, plus MRR over the retrieved depth."""
    n = len(ranks)
    out = {f"hit@{k}": sum(r is not None and r <= k for r in ranks) / n for k in REPORT_KS}
    out["mrr"] = sum(1 / r for r in ranks if r) / n
    return out


def _filters(gold: GoldQuestion):
    from app.edgar_research.infrastructure.repositories.chunk_repo import ChunkSearchFilters

    return ChunkSearchFilters(
        tickers=[gold.ticker],
        filing_types=gold.filing_types,
        filed_after=gold.filed_after,
        filed_before=gold.filed_before,
    )


async def _rank_all(
    golds: list[GoldQuestion], depth: int, decompose: bool = False
) -> tuple[dict[str, dict[str, int | None]], dict[str, DecompositionResult]]:
    """(mode -> question id -> first-hit rank, question id -> decomposition)."""
    from app.edgar_research.application.date_hints import narrow_by_date_hints
    from app.edgar_research.application.embedding_service import EmbeddingService
    from app.edgar_research.application.query_decomposer import QueryDecomposer
    from app.edgar_research.application.repeats import collapse_repeats
    from app.edgar_research.application.retrieval_service import RetrievalService
    from app.edgar_research.application.synonyms import with_filer_terms
    from app.edgar_research.infrastructure.repositories.chunk_repo import ChunkRepository

    repo = ChunkRepository()
    embedder = EmbeddingService()
    vectors = await embedder.embed_many([g.question for g in golds])
    ranks: dict[str, dict[str, int | None]] = {m: {} for m in MODES}
    decompositions: dict[str, DecompositionResult] = {}
    production = RetrievalService(embedder, repo, QueryDecomposer()) if decompose else None
    for gold, vector in zip(golds, vectors):
        flt = narrow_by_date_hints(gold.question, _filters(gold))
        by_vector = await repo.search_by_embedding(query_embedding=vector, k=depth, filters=flt)
        by_keyword = await repo.search_by_text(query=with_filer_terms(gold.question), k=depth, filters=flt)
        pool = 3 * depth
        fused = collapse_repeats(RetrievalService._reciprocal_rank_fusion(
            await repo.search_by_embedding(query_embedding=vector, k=pool, filters=flt),
            await repo.search_by_text(query=with_filer_terms(gold.question), k=pool, filters=flt),
            k=pool,
        ))[:depth]
        for mode, results in (("vector", by_vector), ("keyword", by_keyword), ("hybrid", fused)):
            ranks[mode][gold.id] = first_hit_rank([r.chunk.content for r in results], gold)
        if production:
            chunks, decompositions[gold.id] = await production.retrieve_full(
                gold.question, k=depth, filters=_filters(gold)
            )
            ranks.setdefault("decomposed", {})[gold.id] = first_hit_rank(
                [c.chunk.content for c in chunks], gold
            )
    return ranks, decompositions


def _print_decomposition(decompositions: dict[str, DecompositionResult]) -> None:
    """How many questions the rewrite fired on, and what it cost."""
    from app.shared.cost import UsageSummary, compute_cost
    from app.shared.llm.models import model_for

    usage = UsageSummary()
    for d in decompositions.values():
        usage.input_tokens += d.usage.input_tokens
        usage.output_tokens += d.usage.output_tokens
    rewritten = [i for i, d in decompositions.items() if d.sub_queries != [d.original_query]]
    cost = compute_cost(usage, model_for("decomposer"))
    print(f"\n== decomposer: {len(rewritten)} of {len(decompositions)} questions rewritten, "
          f"{usage.input_tokens} in / {usage.output_tokens} out tokens, "
          f"${cost if cost is not None else '?'}")


def _print_report(golds: list[GoldQuestion], ranks: dict[str, dict[str, int | None]]) -> None:
    tags = sorted({g.tag for g in golds})
    header = "".join(f"{f'hit@{k}':>8}" for k in REPORT_KS) + f"{'mrr':>8}"
    modes = list(ranks)
    for mode in modes:
        print(f"\n== {mode}\n{'tag':16}{'n':>4}{header}")
        for label, group in [("ALL", golds)] + [(t, [g for g in golds if g.tag == t]) for t in tags]:
            s = summarize([ranks[mode][g.id] for g in group])
            print(f"{label:16}{len(group):>4}" + "".join(f"{v:>8.2f}" for v in s.values()))
    print("\n== first-hit rank per question (- = not in top depth)")
    print(f"{'id':36}{'tag':16}" + "".join(f"{m:>11}" for m in modes))
    for g in golds:
        cells = "".join(f"{ranks[m][g.id] or '-':>11}" for m in modes)
        print(f"{g.id:36}{g.tag:16}{cells}")


async def _check_gold(golds: list[GoldQuestion]) -> int:
    """Every answer string must exist in the chunks the question filters to."""
    from app.edgar_research.infrastructure.repositories.db import close_pool, cursor, init_pool

    await init_pool()
    missing = 0
    try:
        for gold in golds:
            flt = _filters(gold)
            async with cursor() as cur:
                await cur.execute(
                    """SELECT content FROM chunks
                       WHERE ticker = %s
                         AND (%s::text[] IS NULL OR filing_type = ANY(%s))
                         AND (%s::date IS NULL OR filed_date >= %s)
                         AND (%s::date IS NULL OR filed_date <= %s)""",
                    (gold.ticker, flt.filing_types, flt.filing_types,
                     flt.filed_after, flt.filed_after, flt.filed_before, flt.filed_before),
                )
                corpus = normalize(" ".join(r["content"] for r in await cur.fetchall()))
            for answer in gold.answers:
                if normalize(answer) not in corpus:
                    missing += 1
                    print(f"MISSING  {gold.id}: {answer!r}")
    finally:
        await close_pool()
    print(f"{len(golds)} questions checked, {missing} answer strings not in the corpus")
    return 1 if missing else 0


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--depth", type=int, default=20)
    parser.add_argument("--decompose", action="store_true",
                        help="also score the production path with query decomposition (LLM calls)")
    parser.add_argument("--check-gold", action="store_true", help="verify answers exist; no API calls")
    args = parser.parse_args()

    load_env()
    golds = load_gold()
    if args.check_gold:
        return await _check_gold(golds)

    from app.edgar_research.infrastructure.repositories.db import close_pool, init_pool

    await init_pool()
    try:
        ranks, decompositions = await _rank_all(golds, args.depth, args.decompose)
        _print_report(golds, ranks)
        if args.decompose:
            _print_decomposition(decompositions)
    finally:
        await close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
