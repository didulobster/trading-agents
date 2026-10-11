# Trading pipeline

Analysts report on a ticker, bull and bear debaters argue over those reports, a risk panel scores the risks, and synthesis turns it all into a decision memo.

## Language

**Evidence pack**:
The analyst reports a debater, risk persona or judge is given, and the only text they may cite.
_Avoid_: context, corpus, sources

**Grounding check**:
A flag saying a figure, quote or stated direction in model output has no support in the evidence pack. The debate and risk panel record it; synthesis rejects the output.
_Avoid_: guard, verifier, fabrication check

## Evaluation

A person judging whether a research run was worth having. Done by hand, outside the pipeline.

**Review**:
One person's written judgement of one research run: their Baseline, five Claim checks, the Finds and Missed, the time spent, and whether they would use the tool again for that kind of decision.
_Avoid_: comparison, eval, scorecard

**Baseline**:
The investor's own view of the ticker, written before the run so the output cannot shape it. Finds and Missed are measured against it.
_Avoid_: prior, my notes

**Claim check**:
One figure from the output, chosen because it would change the decision if wrong, compared by hand against the filing and given exactly one label: Correct, Wrong, Unsupported or Stale.
_Avoid_: fact check, spot check

**Correct**:
The filing states the claim as given, for the period the output says.

**Wrong**:
The filing states something different from the claim.

**Unsupported**:
The passage the output cites does not contain the claim, whether or not the claim is true elsewhere. Unlike a Grounding check, this is a person's judgement against the filing, not the pipeline's automatic flag against the evidence pack.
_Avoid_: ungrounded, hallucinated

**Stale**:
The claim was true for an earlier period but is presented as current.
_Avoid_: outdated

**Find**:
Something in the output that is relevant and accurate but absent from the Baseline.
_Avoid_: insight, new info

**Missed**:
Something that matters to the decision and is absent from the output.
_Avoid_: gap, data gap (a data gap is what the pipeline itself records it could not see)
