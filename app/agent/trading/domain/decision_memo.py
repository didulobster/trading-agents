from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class ResearchManagerPayload(BaseModel):
    """EXACTLY what the Research Manager LLM returns. It synthesizes the
    bull/bear DEBATE ONLY — it never sees the risk-panel ledger, so its
    `preliminary_verdict` is a lean from the debate alone, not the pipeline's
    final answer. No numbers, no quotes: every narrative field cites
    `[C:claim_id]`; Python resolves those and renders their evidence, never
    retyping a figure the model wrote. See infrastructure/synthesis_port.py.
    """

    bull_case: str = Field(description="<=150 words. Cite claims as [C:claim_id].")
    bear_case: str = Field(description="<=150 words. Cite claims as [C:claim_id].")
    thesis: str = Field(
        description=(
            "<=200 words. The debate-level synthesis: which side's evidence is "
            "stronger and why, on the debate alone. Every load-bearing sentence "
            "carries a citation."
        )
    )
    preliminary_verdict: Verdict = Field(
        description=(
            "Your own lean from the bull/bear debate ALONE, before risk review. "
            "The Risk Judge may override this after weighing the risk panel; "
            "that is expected, not a failure of this call."
        )
    )


class RiskJudgePayload(BaseModel):
    """EXACTLY what the Risk Judge LLM returns. It reviews the risk-panel
    ledger AND the Research Manager's preliminary verdict, and its own
    `verdict` is the pipeline's FINAL answer — empowered to override the
    Research Manager's lean when the risk debate warrants it. Cites `[RFnn]`
    for risk factors; may also cite `[C:claim_id]` in `reasoning` when
    explaining agreement or override against the underlying debate. No
    numbers, no quotes, same rule as the Research Manager.
    """

    risk_narrative: str = Field(description="<=200 words. Cite factors as [RF00].")
    reasoning: str = Field(
        description=(
            "<=250 words. The FINAL reasoning behind `verdict` — state plainly "
            "whether you are affirming or overriding the Research Manager's "
            "preliminary_verdict, and why. Every load-bearing sentence cited."
        )
    )
    watch_items: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Observables that would change this read. Each must cite [RF00].",
    )
    verdict: Verdict = Field(description="THE final verdict. buy/sell/hold — no fourth option.")


class DecisionMemo(BaseModel):
    ticker: str
    bull_case: str
    bear_case: str
    # The Research Manager's own debate-level synthesis, kept distinct from
    # `reasoning` (the Risk Judge's FINAL reasoning) so a reader — or an
    # automated check — can see directly whether risk review affirmed or
    # overrode the research lean, rather than that decision being folded
    # invisibly into one paragraph. See synthesis_port.py's two-call split.
    research_thesis: str
    research_preliminary_verdict: Verdict
    risk_debate_summary: str
    technical_signal: str
    reasoning: str
    # Renamed from `suggested_strategy` (Phase 6 plan §8.4, option 1). The
    # project's architecture deliberately excludes trade execution and any
    # fund-manager agent; `suggested_strategy` was the field most likely to
    # drift into actionable advice and quietly reintroduce what that
    # exclusion rules out.
    watch_items: list[str] = []
    verdict: Verdict
    confidence: float
    data_as_of_date: date
    data_gaps: list[str] = []
    assumptions: list[str] = []
    evidence: list[str] = []
