"""Termination guard for the bull/bear debate cycle.

A pure function of state — no I/O, no LLM, no clock. That is what makes it
exhaustively testable: `next_debate_step` can be evaluated over every
reachable input in milliseconds at zero API cost, which is a proof of
termination rather than a sample of it. Five clean live runs are consistent
with a 10%% runaway rate at better-than-even odds; this file is where the
guarantee actually lives.

Three independent layers stop the debate, so no single bug runs away:

  1. `n >= MAX_TURNS` here                       — normal operation
  2. `recursion_limit` in the CLI invoke config  — a router bug
  3. runtime asserts at node entry               — a wiring bug that
     (see application/debate_nodes.py)             bypassed the router
"""

from app.agent.trading.application.nodes import ANALYST_OUTPUTS

MAX_ROUNDS = 3
MAX_TURNS = 2 * MAX_ROUNDS

# Consecutive turns introducing no new claim_id before the debate is called
# finished. Two, because one side repeating itself is a bad turn and both
# sides repeating themselves is the end of the argument.
UNPRODUCTIVE_STOP = 2


def next_debate_step(state) -> str:
    """Returns 'bull' | 'bear' | 'done'.

    Used as the conditional-edge router for BOTH debate nodes and for the
    analyst -> debate entry edge. The entry edge is conditional for a reason:
    a plain edge into bull_turn would execute one turn before any router ever
    saw the state, so the no-evidence case below could not skip the debate.
    """
    turns = state.get("debate_turns") or []
    n = len(turns)

    # Layer 1 — the hard cap. First, unconditional, and it cannot raise.
    # Ordering is load-bearing: if the productivity check ran first and threw
    # on a malformed turn, control would fall through to the alternation
    # branch below and loop forever.
    if n >= MAX_TURNS:
        return "done"

    # No evidence -> no debate. A `--only` run that excluded every analyst leg
    # would otherwise produce a debate over an empty pack: two models arguing
    # from nothing, which reads like a debate and is theatre. Same principle
    # as the news caveats — absence of evidence is not neutrality.
    if n == 0 and all(state.get(key) is None for key in ANALYST_OUTPUTS.values()):
        return "done"

    if n >= UNPRODUCTIVE_STOP and all(
        not t.productive for t in turns[-UNPRODUCTIVE_STOP:]
    ):
        return "done"

    return "bull" if n % 2 == 0 else "bear"


def termination_reason(state) -> str:
    """Why the debate stopped. Only meaningful once `next_debate_step` has
    returned 'done' — called by debate_close_node at exactly that point."""
    turns = state.get("debate_turns") or []
    if len(turns) >= MAX_TURNS:
        return "round_cap"
    if not turns:
        return "no_evidence"
    return "unproductive"
