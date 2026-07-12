
from eval.extract_runner import ExtractionCaseResult


def extraction_report(results: list[ExtractionCaseResult]) -> str:
    lines: list[str] = []
    total_passed = 0
    total_failed = 0

    for case in results:
        lines.append(f"\n{case.ticker} {case.fiscal_period} ({case.filed_date})")
        for r in case.field_results:
            if r.actual is None:
                lines.append(f"  FAIL  {r.field:<25} got null — retrieval gap or not_disclosed")
                total_failed += 1
            elif r.passed:
                lines.append(f"  PASS  {r.field:<25} {r.actual} (expected {r.expected})")
                total_passed += 1
            else:
                lines.append(
                    f"  FAIL  {r.field:<25} got {r.actual}, expected {r.expected} "
                    f"(delta={r.delta:.1f}, conf={r.confidence})"
                )
                total_failed += 1

    lines.append(f"\n{'─' * 50}")
    lines.append(f"Results: {total_passed} passed, {total_failed} failed "
                 f"out of {total_passed + total_failed} checks")

    return "\n".join(lines)

def serialize_extraction_result(r: ExtractionCaseResult) -> dict:
    return {
        "ticker": r.ticker,
        "fiscal_period": r.fiscal_period,
        "filed_date": r.filed_date.isoformat(),
        "passed": r.passed,
        "field_results": [
            {
                "field": fr.field,
                "expected": fr.expected,
                "actual": fr.actual,
                "passed": fr.passed,
                "delta": fr.delta,
                "confidence": fr.confidence,
            }
            for fr in r.field_results
        ],
    }
