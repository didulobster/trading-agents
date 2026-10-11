# Trading pipeline

Analysts report on a ticker, bull and bear debaters argue over those reports, a risk panel scores the risks, and synthesis turns it all into a decision memo.

## Language

**Evidence pack**:
The analyst reports a debater, risk persona or judge is given, and the only text they may cite.
_Avoid_: context, corpus, sources

**Grounding check**:
A flag saying a figure, quote or stated direction in model output has no support in the evidence pack. The debate and risk panel record it; synthesis rejects the output.
_Avoid_: guard, verifier, fabrication check

**Decision memo**:
Synthesis's final output for one ticker: a buy, sell or hold verdict, or UNRESOLVED when repeated judgments don't agree.
_Avoid_: memo, report, recommendation

**Fundamentals report**:
The analyst report trading makes from a fundamentals memo, and the form in which it enters the evidence pack.
_Avoid_: fundamentals memo, fundamentals analysis
