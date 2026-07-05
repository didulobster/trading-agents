# eval/report.py
from collections import defaultdict

from eval.runner import QuestionResult


def report(results: list[QuestionResult]) -> str:
    by_category: dict[str, list[QuestionResult]] = defaultdict(list)
    for r in results:
        by_category[r.category].append(r)

    header = (
        f"{'category':<32} {'N':>3} "
        f"{'S@5':>6} {'S@10':>6} "
        f"{'C@5':>6} {'C@10':>6} "
        f"{'R@5':>6} {'R@10':>6} {'MRR':>6}"
    )
    lines = ["=== Retrieval Eval Report ===", ""]
    lines.append(header)
    lines.append("-" * len(header))

    for category, qs in sorted(by_category.items()):
        n = len(qs)
        s5 = sum(q.success_at_5 for q in qs) / n
        s10 = sum(q.success_at_10 for q in qs) / n
        c5 = sum(q.coverage_at_5 for q in qs) / n
        c10 = sum(q.coverage_at_10 for q in qs) / n
        r5 = sum(q.recall_at_5 for q in qs) / n
        r10 = sum(q.recall_at_10 for q in qs) / n
        mrr = sum(q.reciprocal_rank for q in qs) / n
        lines.append(
            f"{category:<32} {n:>3} "
            f"{s5:>6.3f} {s10:>6.3f} "
            f"{c5:>6.3f} {c10:>6.3f} "
            f"{r5:>6.3f} {r10:>6.3f} {mrr:>6.3f}"
        )

    lines.append("-" * len(header))
    n = len(results)

    overall_s5 = sum(q.success_at_5 for q in results) / len(results)
    overall_s10 = sum(q.success_at_10 for q in results) / len(results)
    overall_c5 = sum(q.coverage_at_5 for q in results) / n
    overall_c10 = sum(q.coverage_at_10 for q in results) / n
    overall_r5 = sum(q.recall_at_5 for q in results) / len(results)
    overall_r10 = sum(q.recall_at_10 for q in results) / len(results)
    overall_mrr = sum(q.reciprocal_rank for q in results) / len(results)
    lines.append(
        f"{'overall':<32} {n:>3} "
        f"{overall_s5:>6.3f} {overall_s10:>6.3f} "
        f"{overall_c5:>6.3f} {overall_c10:>6.3f} "
        f"{overall_r5:>6.3f} {overall_r10:>6.3f} {overall_mrr:>6.3f}"
    )
    # Per-question failure detail
    lines.append("")
    lines.append("=== Failures (recall@10 = 0) ===")
    for r in results:
        if r.recall_at_10 == 0:
            lines.append(f"  {r.question_id} [{r.category}]: {r.question}")
            lines.append(f"    got:  {r.retrieved_chunks[:5]}...")

    return "\n".join(lines)