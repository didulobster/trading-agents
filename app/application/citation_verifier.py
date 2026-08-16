"""
Citation verification.

Checks that every numeric literal and quoted string in a generated answer
actually appears in at least one of the chunks that were retrieved to
produce it.

SCOPE — read this before trusting it:
  Catches   : fabricated figures, fabricated quotations.
  Misses    : fabricated causation ("new Eurobond issuance drove the
              increase"), and any claim with no literal to check.

The verifier answers "does this number exist in the source material", not
"is this claim true". Those are different questions and only the first is
mechanically decidable.

Wrong fiscal-year attribution of a real figure used to be an unmitigated
miss here too — a value from one period, mislabeled and used as another
period's input, is individually real and passes this check every time.
That specific case is now caught one layer upstream, in
validate_calculate_inputs (app/agent/tools.py, check 4): every calculate()
input declares a fiscal_period, and that check confirms the declared
period's year actually appears near where the value was retrieved. This
verifier still can't catch a mislabeled figure that never went through
calculate() — e.g. a raw retrieved number stated directly in prose without
a computation. That gap remains open.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# What we pull out of an answer
# ---------------------------------------------------------------------------

# Numbers with optional thousands separators and decimals: 27,558.5  1364.1  118
_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")

def _extract_quotes(text: str) -> list[tuple[str, int]]:
    """
    Pair quote characters sequentially (1st-2nd, 3rd-4th, ...) and return
    spans of >= 4 words with their start offsets.

    A regex like ["“]([^"”]{15,}?)["”] pairs the CLOSING quote of a short
    quotation with the OPENING quote of the next one, capturing the prose
    between them. Observed: 'measures being "put in place" (FY2025 10-K) to
    being "completed"' yielded ' (FY2025 10-K) to being ' as a quotation.
    """
    positions = [m.start() for m in re.finditer(r"[\"\u201c\u201d]", text)]
    out: list[tuple[str, int]] = []
    for i in range(0, len(positions) - 1, 2):
        start, end = positions[i], positions[i + 1]
        span = text[start + 1 : end]
        if len(span.split()) >= 4 and len(span) >= 15:
            out.append((span, start))
    return out

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



_CORPUS_NUM_RE = re.compile(r"-?\(?[\d,]+\.?\d*\)?")


def _corpus_values(corpus: str) -> list[float]:
    """Every number in the corpus, as floats. Parenthesised = negative."""
    out: list[float] = []
    for m in _CORPUS_NUM_RE.finditer(corpus):
        s = m.group().strip()
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()").replace(",", "")
        if not s or s in {".", "-"}:
            continue
        try:
            v = float(s)
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


def _matches_with_scale(value: float, corpus_values: list[float]) -> bool:
    """
    True if `value` matches a corpus figure directly or after a unit change.

    Filings that report in thousands are routinely restated in millions in a
    memo: the corpus holds 877,433 and the memo says 877.4. Comparison is
    numeric with a tolerance sized to the memo's precision, not string-based.
    """
    av = abs(value)
    for c in corpus_values:
        ac = abs(c)
        if ac == av:
            return True
        # corpus in thousands, memo in millions (and the reverse)
        for scale in (1000.0, 1_000_000.0):
            if ac and abs(ac / scale - av) <= max(0.05, av * 0.0005):
                return True
            if av and abs(av / scale - ac) <= max(0.05, ac * 0.0005):
                return True
    return False


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
    _corpus_nums = _corpus_values("\n".join(chunk_texts.values()))

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
        if hit is None:
            # Fall back to scale-aware numeric comparison (thousands vs millions)
            try:
                if _matches_with_scale(float(bare), _corpus_nums):
                    hit = -2
            except ValueError:
                pass

        f = Finding("number", raw, context, hit)
        (report.verified if hit is not None else report.unverified).append(f)

    # --- quotes ------------------------------------------------------------
    for quoted, qstart in _extract_quotes(answer):
        needle = _normalize_text(quoted)
        start = max(0, qstart - 30)
        context = answer[start : qstart + len(quoted) + 32].replace("\n", " ")

        hit = None
        for cid, text in normalized_chunks.items():
            if needle in text:
                hit = cid
                break

        f = Finding("quote", quoted[:70], context, hit)
        (report.verified if hit is not None else report.unverified).append(f)

    return report