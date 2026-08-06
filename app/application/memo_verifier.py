"""Verify the final memo against everything the tools returned this run."""

from app.application.citation_verifier import verify_answer


def verify_memo(memo: str, provenance_corpus: str,
                computed_values: list[float]) -> str:
    if not provenance_corpus.strip():
        return memo

    report = verify_answer(memo, {0: provenance_corpus},
                           computed_values=computed_values)
    if report.ok:
        return memo

    lines = [
        "", "---", "",
        "## Unverified Figures and Quotations", "",
        "The following appear in this memo but were not returned by any "
        "tool during this run. Verify against the filing before relying "
        "on them.", "",
    ]
    for f in report.unverified:
        label = "quote" if f.kind == "quote" else "figure"
        lines.append(f"- **{label}:** `{f.value}`")
        lines.append(f"  - context: …{f.context.strip()}…")

    return memo + "\n".join(lines)