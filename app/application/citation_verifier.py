"""
Citation verification.

Checks that every numeric literal and quoted string in a generated answer
actually appears in at least one of the chunks that were retrieved to
produce it.

SCOPE — read this before trusting it:
  Catches   : fabricated figures, fabricated quotations.
  Misses    : fabricated causation ("new Eurobond issuance drove the
              increase"), wrong fiscal-year attribution of a real figure,
              and any claim with no literal to check.

The verifier answers "does this number exist in the source material", not
"is this claim true". Those are different questions and only the first is
mechanically decidable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# What we pull out of an answer
# ---------------------------------------------------------------------------

# Numbers with optional thousands separators and decimals: 27,558.5  1364.1  118
_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")

# Double-quoted spans of >= 4 words — the shape of a claimed filing quotation.
# Shorter quoted fragments are usually terminology, not quotation.
_QUOTE_RE = re.compile(r"[\"“]([^\"”]{15,}?)[\"”]")

# Figures that are almost always structural rather than sourced: years,
# percentages of the model's own construction, list numbering, small counts.
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


@dataclass
class Finding:
    kind: str                  # "number" | "quote"
    value: str                 # as it appeared in the answer
    context: str               # surrounding text, for the report
    matched_chunk_id: int | None = None


@dataclass
class VerificationReport:
    verified: list[Finding] = field(default_factory=list)
    unverified: list[Finding] = field(default_factory=list)
    skipped: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unverified

    def summary(self) -> str:
        lines = [
            f"Citation check: {len(self.verified)} verified, "
            f"{len(self.unverified)} UNVERIFIED, {len(self.skipped)} skipped"
        ]
        for f in self.unverified:
            lines.append(f"  UNVERIFIED {f.kind}: {f.value}")
            lines.append(f"      context: …{f.context}…")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Normalization — the part that decides whether this is useful or noisy
# ---------------------------------------------------------------------------

def _number_variants(raw: str) -> set[str]:
    """
    Every string form a filing might use for the number an answer writes
    as `raw`. Filings write 27,558.5; answers write 27558.5 or 27,558.5.
    Filings also write 1,364.1 where an answer may write 1364.
    """
    bare = raw.replace(",", "")
    variants = {raw, bare}

    try:
        val = float(bare)
    except ValueError:
        return variants

    # comma-grouped form
    if val == int(val):
        variants.add(f"{int(val):,}")
        variants.add(str(int(val)))
    else:
        variants.add(f"{val:,}")
        # trailing-zero and one-decimal forms: 1364.10 -> 1364.1
        variants.add(f"{val:,.1f}")
        variants.add(f"{val:.1f}")
        variants.add(f"{val:,.2f}")

    return {v for v in variants if v}


def _normalize_text(s: str) -> str:
    """Collapse whitespace and smart quotes so quote matching survives
    the line breaks and typography of parsed filing text."""
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u2014", "-").replace("\u2013", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def _should_skip_number(raw: str, context: str) -> bool:
    bare = raw.replace(",", "")

    # Years are structural, and appear in citation tags the model constructs.
    if _YEAR_RE.match(bare):
        return True

    # Section references: "Item 1A", "Item 7". Only the section number
    # itself is skipped — not every number that happens to sit near one.
    if re.search(rf"Item\s+{re.escape(raw)}\b", context):
        return True

    try:
        val = float(bare)
    except ValueError:
        return True

    # Small integers are almost always enumeration, section numbers, or
    # counts the model constructed ("three risk factors", "1.", "top 5").
    if val == int(val) and val < 100:
        return True

    return False


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def _computed_forms(values) -> set[str]:
    """String forms a calculate() result may take in the answer text."""
    out: set[str] = set()
    for v in values or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        out.update({f"{f:.1f}", f"{f:.2f}", str(round(f, 1)), str(round(f, 2))})
    return out


def verify_answer(
    answer: str,
    chunk_texts: dict[int, str],
    computed_values: list[float] | None = None,
) -> VerificationReport:
    """
    answer          : the generated answer text
    chunk_texts     : {chunk_id: full chunk content} for every chunk
                      retrieved to produce this answer
    computed_values : results returned by calculate() during this run.
                      Without these, every legitimately computed ratio is
                      reported unverified and the report becomes noise.

    Returns a VerificationReport. `unverified` is what needs a human look.
    """
    report = VerificationReport()
    computed = _computed_forms(computed_values)

    normalized_chunks = {cid: _normalize_text(t) for cid, t in chunk_texts.items()}
    raw_chunks = {cid: t for cid, t in chunk_texts.items()}

    # --- numbers -----------------------------------------------------------
    seen_numbers: set[str] = set()
    for m in _NUMBER_RE.finditer(answer):
        raw = m.group().rstrip(".")
        if not raw or raw in seen_numbers:
            continue
        seen_numbers.add(raw)

        start = max(0, m.start() - 45)
        context = answer[start : m.end() + 45].replace("\n", " ")

        if _should_skip_number(raw, context):
            report.skipped.append(Finding("number", raw, context))
            continue

        # A figure matching a calculate() result is verified as computed,
        # not fabricated. chunk id -1 marks "produced by the calculator".
        bare = raw.replace(",", "")
        if bare in computed or _computed_forms([bare]) & computed:
            report.verified.append(Finding("computed", raw, context, -1))
            continue

        variants = _number_variants(raw)
        hit = None
        for cid, text in raw_chunks.items():
            if any(v in text for v in variants):
                hit = cid
                break

        f = Finding("number", raw, context, hit)
        (report.verified if hit is not None else report.unverified).append(f)

    # --- quotes ------------------------------------------------------------
    for m in _QUOTE_RE.finditer(answer):
        quoted = m.group(1)
        if len(quoted.split()) < 4:
            continue

        needle = _normalize_text(quoted)
        start = max(0, m.start() - 30)
        context = answer[start : m.end() + 30].replace("\n", " ")

        hit = None
        for cid, text in normalized_chunks.items():
            if needle in text:
                hit = cid
                break

        f = Finding("quote", quoted[:70], context, hit)
        (report.verified if hit is not None else report.unverified).append(f)

    return report