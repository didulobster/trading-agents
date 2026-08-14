from datetime import date
from enum import Enum
from pydantic import BaseModel

class Verdict(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

class DecisionMemo(BaseModel):
    ticker: str
    bull_case: str
    bear_case: str
    risk_debate_summary: str
    technical_signal: str
    reasoning: str
    suggested_strategy: str
    verdict: Verdict
    confidence: float
    data_as_of_date: date
    data_gaps: list[str] = []
    assumptions: list[str] = []
    evidence: list[str] = []