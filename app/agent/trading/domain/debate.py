"""Phase 5 domain types for the bull/bear debate.

Same rule as the Phase 4 index-join: the model produces argument *content*;
Python owns every index, counter and side label. If the LLM emitted its own
`round_num`, the termination guard would be reading a field the model can
fabricate — and the guard is the only thing standing between a debate and an
unbounded loop.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Side = Literal["bull", "bear"]
Stance = Literal["hold", "sharpen", "concede"]

# Which analyst report a claim is drawn from. "none" is a first-class value,
# not a fallback: an argument built on top of other claims is legitimate, and
# calling it report-backed when it isn't is the fabrication this enum exists
# to make visible.
EvidenceRef = Literal["fundamentals", "technical", "news", "sentiment", "none"]


# Deliberately flat, and the docstring below is deliberately short: both of
# these are shipped to the model as part of the tool `input_schema`, so
# implementation notes written here become prompt text. Nesting a model
# inside a model inside a model also makes `model_json_schema()` emit deeper
# `$defs`/`$ref` chains, which debate_port has to inline before sending; one
# level keeps that walk trivial.
# The model cannot reliably emit an empty string into a tool call. Asked for
# one it writes a stray "</antml parameter>" marker instead, and that landed
# in `concession_trigger` on 4 of 4 live turns — which then tripped the
# concession guard on a turn that was not conceding anything. Asking for the
# literal 'none' produced a clean first attempt every time.
#
# So the wire protocol uses a sentinel and Python normalizes it back: "" stays
# the internal meaning of "absent", and nothing downstream has to know. A
# genuine quote consisting of the single word "none" is unreachable through
# this, which is a trade worth making.
_BLANK_SENTINELS = frozenset({"none", "null", "n/a", ""})


def _normalize_blank(value: object) -> object:
    if isinstance(value, str) and value.strip().lower() in _BLANK_SENTINELS:
        return ""
    return value


class DebateClaim(BaseModel):
    """One atomic assertion, backed by a report or by other claims."""

    claim_id: str = Field(
        description=(
            "Short stable slug, e.g. 'vmware-amort-rolloff'. Reuse the SAME id "
            "when restating a claim made in an earlier turn."
        )
    )
    text: str = Field(description="One sentence.")
    evidence_ref: EvidenceRef = Field(
        description=(
            "'none' = reasoning over other claims, not a report-backed fact."
        )
    )
    evidence_quote: str = Field(
        default="",
        description=(
            "Verbatim span (<=25 words) copied from that report. The literal "
            "string 'none' when evidence_ref='none'. Never an empty string, "
            "and never spliced or elided with '...'."
        ),
    )

    _blank = field_validator("evidence_quote", mode="before")(
        lambda v: _normalize_blank(v)
    )


class DebateTurnPayload(BaseModel):
    """EXACTLY what the LLM returns. No indices, no counters, no side."""

    stance: Stance
    concession_trigger: str = Field(
        default="",
        description=(
            "The opposing claim_id that moved you. The literal string 'none' "
            "unless stance='concede'. Never an empty string."
        ),
    )
    argument: str = Field(description="<=200 words.")
    # The bound is stated in the description as well as enforced by pydantic:
    # strict tool schemas reject minItems/maxItems, so the model only learns
    # the range from prose. Pydantic still rejects a violation after the
    # fact — the schema is guidance, the model is the validator.
    claims: list[DebateClaim] = Field(
        min_length=1,
        max_length=5,
        description="Between 1 and 5 claims. Never zero, never more than five.",
    )
    rebuts: list[str] = Field(
        default_factory=list,
        description=(
            "Opponent claim_ids you are directly attacking. Empty on turn 0 only."
        ),
    )

    _blank = field_validator("concession_trigger", mode="before")(
        lambda v: _normalize_blank(v)
    )


class DebateTurn(BaseModel):
    """Payload plus Python-owned metadata. This is what enters TradingState."""

    turn_index: int          # 0-based, assigned by Python
    round_num: int           # (turn_index // 2) + 1, assigned by Python
    side: Side               # assigned by Python from which node ran
    payload: DebateTurnPayload

    # Did this turn introduce a claim_id nobody had used yet? Two consecutive
    # false values end the debate — see application/debate_router.py.
    productive: bool = True

    # Per-turn findings live here rather than in a state channel: a cyclic
    # node cannot write to a plain overwrite channel without clobbering its
    # own earlier turns, and adding a second reducer would be a second source
    # of truth for the same content. The synthesizer aggregates across turns.
    guard_flags: list[str] = Field(default_factory=list)
    unquoted_evidence: list[str] = Field(default_factory=list)

    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float | None = None
