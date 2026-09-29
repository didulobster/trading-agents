"""The LLM side of the bull/bear debate: one forced tool call, the
debate-specific guardrails, and the vault transcript. The evidence pack and
the grounding checks live in evidence.py.

Structured output follows the direct-SDK pattern the Phase 3/4 ports use — a
single tool with a forced `tool_choice`, validated by pydantic — rather than
free text that has to be parsed back. The model produces argument content and
nothing else; every index, counter and side label is assigned in Python.

On guardrails: the consistent finding in the multi-agent-debate literature
(Du et al. 2023; Liang et al. 2023 on Degeneration-of-Thought; the sycophancy
work) is that debate reliably produces CONVERGENCE, and convergence is not
evidence of correctness. Two instances of one base model drift toward
agreement because agreement is what the pretraining distribution rewards.
Directions recalled rather than re-read — verify before citing any of it.
Four of the five counters here are enforced by pydantic or Python, because a
prompt-only guardrail is the kind that degrades silently.

Debate has the opposite failure mode too, and this module found it: total
entrenchment. Across all 42 vault transcripts, 249 turns are `hold` or
`sharpen` and NOT ONE is `concede`, while debaters concede in the argument
prose. `check_concession`'s docstring has the diagnosis. Half the fix there is
structural (a partial concession is now expressible and still validated); the
other half — getting the model to route a prose concession into
`concession_trigger` — is prompt-only and therefore exactly the kind of
guardrail this module distrusts. It is written that way ON PURPOSE: the
alternative is scanning the argument text for "I concede", and that does not
work. Of 21 occurrences of the word across the vault, 18 are a debater saying
the OPPONENT concedes something (an attack, the opposite of a concession) and
one is a negation ("None of this is a reason to concede..."). A keyword
counter would report ~21 concessions where there are 2 and invert the
direction of 18 of them. So the prompt asks, and the reporting side states
plainly what a zero means rather than claiming nobody moved.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# create_with_temperature_fallback lives with the clients now, so the query
# decomposer can use it too; re-exported for risk_port and synthesis_port.
from app.agent.trading.infrastructure.structured_call import (
    assert_within_budget,
    call_with_schema_retry,
    force_crash,
    inline_refs,
)
# create_with_temperature_fallback is re-exported on purpose: risk_port and
# the determinism scripts import it from here, and several tests patch it
# at this name. It reads as unused to a naive import scan; it is not — the
# noqa is what stops `ruff --fix` from deleting it, which it did once.
from app.infrastructure.llm import (  # noqa: F401
    LLMClient,
    create_with_temperature_fallback,
    get_client,
)
from app.infrastructure.llm.models import model_for, warn_if_unpriced

from app.agent.researcher import (
    UsageSummary,
    _save_output,
    log_cost,
)
from app.agent.trading.domain.debate import (
    DebateTurn,
    DebateTurnPayload,
    Side,
    canonical_claims,
)
from app.agent.trading.domain.sanitize import EXTERNAL_TEXT_FRAMING
from app.agent.trading.infrastructure.cost_log import new_event_id, record_cost_event
from app.agent.trading.infrastructure.evidence import (
    build_evidence_pack,
    contradicted_directions,
    quotable_texts,
    quote_is_backed,
    unbacked_figures,
)

# The project-wide model from .env (LLM_CLAUDE_MODEL), same as every other
# node. TRADING_DEBATE_MODEL still overrides it for a one-off run without
# moving the whole pipeline.
#
# Worth knowing what this trades away: the debate is the one phase where
# reasoning quality IS the deliverable. A bull that cannot construct a real
# counterargument produces a transcript that looks like a debate and isn't,
# and that failure is invisible to both exit criteria — they test
# termination and resume, not argument quality. Read a transcript by hand
# after changing this, because no assertion here will tell you.
DEBATE_MODEL = model_for("debate")

# Room for adaptive thinking plus the tool call. Thinking tokens count
# against this, so the 1200 that fit a text-only turn does not fit here.
DEBATE_MAX_TOKENS = 4000

# Whole-debate ceiling, not per turn. Deliberately model-independent: it is a
# runaway and prompt-bloat trip wire, not a target, so it stays put when
# LLM_CLAUDE_MODEL moves.
#
# MEASURED, six turns over the technical report alone (AVGO, 2026-08-23):
#   claude-sonnet-5   $0.1506 total, ~$0.025/turn, 80s wall clock
#   claude-haiku-4-5  ~$0.005/turn, so ~$0.03 for the same six turns
# Input grows ~1.8k/turn as the transcript does. A full four-report pack will
# be dearer than either figure; re-measure before treating 0.35 as a margin
# rather than a ceiling.
DEBATE_BUDGET_USD = 0.35

# Thinking ON, effort LOW — where the model supports it. This started as
# {"type": "disabled"} on the reasoning that one forced tool call with a
# <=200 word argument has nothing for a thinking budget to buy. Two live
# turns disproved it: BOTH first attempts came back with `stance` missing and
# a serialized "...</submit_argument>" string stuffed inside `argument` — the
# model had half-written the tool call as text. That is the documented
# thinking-disabled failure mode, and it cost a retry on 2 of 2 turns.
DEBATE_THINKING: dict[str, Any] = {"type": "adaptive"}
DEBATE_EFFORT = "low"

# Adaptive thinking and output_config.effort exist on the 4.6-and-later
# families and are REJECTED by 4.5-era models — Haiku 4.5 and Sonnet 4.5 take
# the older {"type": "enabled", "budget_tokens": N} form and error on
# `effort` outright. Now that DEBATE_MODEL follows LLM_CLAUDE_MODEL, which
# points at Haiku 4.5 today, sending them unconditionally would 400 every
# turn.
#
# Prefixes rather than a version comparison, because the id format is not a
# reliable ordering ("claude-sonnet-5" sorts below "claude-sonnet-4-6"), and
# an UNKNOWN id falls through to sending NEITHER: omitting both is valid on
# every model while sending them is not, so the safe default is the one that
# still runs. A model added here without checking gets a 400 on the first
# turn, which is loud and cheap.
_ADAPTIVE_THINKING_MODELS = (
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)


def supports_adaptive_thinking(model: str) -> bool:
    return model.startswith(_ADAPTIVE_THINKING_MODELS)


def reasoning_config(model: str, temperature: float | None) -> dict:
    """The `thinking`/`output_config`/`temperature` kwargs for one call.

    Production (`temperature=None`, the default everywhere this is called):
    unchanged behavior — adaptive thinking on for the models that support it,
    no explicit `temperature` sent at all.

    An EXPLICIT temperature (Phase 6's determinism/stability checks, which
    need `temperature=0` and a fixed low temperature respectively) disables
    thinking outright, on every model, regardless of the value requested.
    Extended/adaptive thinking requires the API's default temperature and
    rejects an explicit one alongside it — sending both is a 400, and a
    reproducibility check that intermittently 400s on the very call it is
    trying to make deterministic is worse than no check. Determinism claims
    about the *thinking-enabled* production path are therefore a
    correlational claim of "this held with thinking off", not a proof that
    holds with it on — recorded in the finding, not hidden by it.
    """
    if temperature is not None:
        return {"temperature": temperature}
    if supports_adaptive_thinking(model):
        return {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}
    return {}


warn_if_unpriced(DEBATE_MODEL, "debate", DEBATE_BUDGET_USD)

# Forced-failure hooks for the resume tests. Deliberately in the port rather
# than the node: variant B has to die AFTER the API call and before the node
# returns, which is the window a `kill -9` would land in and the one the
# add-reducer's re-execution behaviour is actually tested by.
_CRASH_AT = os.getenv("DEBATE_CRASH_AT_TURN")
_CRASH_WHEN = os.getenv("DEBATE_CRASH_WHEN", "before")   # "before" | "after"


def _maybe_crash(turn_index: int, when: str) -> None:
    if _CRASH_AT is None or int(_CRASH_AT) != turn_index or _CRASH_WHEN != when:
        return
    force_crash("debate", f"{when} turn {turn_index} (DEBATE_CRASH_AT_TURN)")


# ---------------------------------------------------------------------------
# Prompts — symmetric by construction
# ---------------------------------------------------------------------------
#
# Both sides are built from one template with a single stance slot, so
# `BULL_SYSTEM.replace(BULL_STANCE, "") == BEAR_SYSTEM.replace(BEAR_STANCE,
# "")` holds structurally rather than by anyone remembering to mirror an
# edit. Asserted as a unit test: any asymmetry becomes a permanent confound
# in every transcript reasoned over later, and it goes invisible after a few
# prompt edits.

BULL_STANCE = """\
You argue the BULL case: that the evidence supports owning this security.
Your opponent argues the bear case."""

BEAR_STANCE = """\
You argue the BEAR case: that the evidence argues against owning this security.
Your opponent argues the bull case."""

_SYSTEM_TEMPLATE = """\
You are one side of a structured, adversarial equity research debate.

{STANCE}

You will be given an EVIDENCE PACK containing the analyst reports produced for
this ticker, and the transcript of the debate so far. Argue from the pack.

{EXTERNAL_TEXT_FRAMING}

HARD RULES — these are checked in code after you answer:

1. EVERY figure you write must appear VERBATIM in the evidence pack. Do not
   compute, re-derive, annualize, or restate a number in a different unit.
   Your job is to cite the analysts' numbers, not to produce new ones. A
   figure you derived is, by construction, unbacked.
1a. Where the pack gives a "Computed relations" block, those comparisons are
   worked out in code and are AUTHORITATIVE. State them as given. Do not
   work out a comparison yourself from the raw indicator values, and never
   contradict the block — including the bands it names, such as whether RSI
   is overbought or oversold. A relation line is also the cleanest thing to
   quote for a claim about two values, because it carries both.
2. Every claim carries an `evidence_ref`. If the claim rests on a report,
   name that report and quote it: `evidence_quote` must be a VERBATIM,
   CONTIGUOUS span of at most 25 words copied out of that report — never two
   fragments joined with "...". If the claim is reasoning over other claims
   rather than a report-backed fact, set evidence_ref='none' and
   evidence_quote='none'.
   NEVER send an empty string for any field. Where a field does not apply,
   send the literal string 'none'.
3. `claim_id` is a short stable slug. When you restate a claim you or your
   opponent already made, REUSE THE EXISTING id. Invent a new id only for a
   genuinely new assertion.
4. `rebuts` lists the opponent claim_ids you are directly attacking. It may
   be empty only on the opening turn.
5. Stance — your OVERALL posture this turn:
   - 'hold'    — you are maintaining your position against the rebuttal.
   - 'sharpen' — you are narrowing or qualifying your own earlier claim.
   - 'concede' — the opposing claim has overturned your position. Rare.
6. `concession_trigger` is a SEPARATE axis from stance. It names the ONE
   opponent claim_id you are accepting as correct this turn, and it applies
   on ANY stance. Accepting a point you cannot answer while holding your
   overall case is the normal, expected shape: stance='hold' with
   `concession_trigger` naming that claim. Reserve stance='concede' for the
   rarer case where accepting it overturns your side.
   IF YOUR ARGUMENT TEXT ACCEPTS AN OPPOSING POINT — "I concede X", "that is
   a genuine overhang", "the bear is right about X", "X is real but" — YOU
   MUST NAME THAT CLAIM'S id IN `concession_trigger`. A concession written
   only in prose is invisible to everything downstream, which then reports
   that neither side moved. The id must be an OPPONENT claim_id already in
   the transcript; your own earlier claim is not a concession, and neither
   is an id nobody made. If you accepted nothing this turn, send 'none'.

A report marked "NOT RUN" is missing evidence, not neutral evidence. Do not
infer anything from its absence, and do not argue from it in either direction.

Do not concede to be agreeable, and do not manufacture disagreement. If the
evidence genuinely does not support your side on a point, name it in
`concession_trigger` and argue the points where it does.

Call `submit_argument` exactly once. Say nothing else."""

BULL_SYSTEM = _SYSTEM_TEMPLATE.replace("{STANCE}", BULL_STANCE).replace(
    "{EXTERNAL_TEXT_FRAMING}", EXTERNAL_TEXT_FRAMING
)
BEAR_SYSTEM = _SYSTEM_TEMPLATE.replace("{STANCE}", BEAR_STANCE).replace(
    "{EXTERNAL_TEXT_FRAMING}", EXTERNAL_TEXT_FRAMING
)

_STANCE_BY_SIDE = {"bull": BULL_STANCE, "bear": BEAR_STANCE}
_SYSTEM_BY_SIDE = {"bull": BULL_SYSTEM, "bear": BEAR_SYSTEM}


def render_transcript(turns: list[DebateTurn]) -> str:
    """The debate so far, as the next speaker sees it."""
    if not turns:
        return "TRANSCRIPT: empty — this is the opening turn."
    lines = ["TRANSCRIPT SO FAR:"]
    for turn in turns:
        lines.append(
            f"\n[turn {turn.turn_index} · round {turn.round_num} · "
            f"{turn.side.upper()} · stance={turn.payload.stance}"
            + (
                f" · concedes to {turn.payload.concession_trigger}"
                + ("" if turn.payload.stance == "concede" else " (partial)")
                if turn.payload.concession_trigger
                else ""
            )
            + "]"
        )
        lines.append(turn.payload.argument)
        for claim in turn.payload.claims:
            quote = f' "{claim.evidence_quote}"' if claim.evidence_quote else ""
            lines.append(
                f"  · {claim.claim_id} [{claim.evidence_ref}]: {claim.text}{quote}"
            )
        if turn.payload.rebuts:
            lines.append(f"  rebuts: {', '.join(turn.payload.rebuts)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------

SUBMIT_TOOL = {
    "name": "submit_argument",
    "description": "Submit this turn's argument. Call exactly once.",
    # strict, so tool_use.input is guaranteed to match the schema. Without it
    # the first attempt at a turn came back flattened — the DebateClaim
    # fields hoisted to the top level beside `argument`, `stance` missing
    # entirely — on 3 of 3 live turns, costing a retry every time. A retry
    # loop is the one runaway the round cap cannot see, so removing the
    # reason to retry is worth more than handling the retry well.
    "strict": True,
    "input_schema": inline_refs(DebateTurnPayload.model_json_schema()),
}


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def check_quotes(payload: DebateTurnPayload, texts: dict[str, str]) -> list[str]:
    """claim_ids whose evidence_quote is not actually in the report it names.

    Same class of gap as Phase 4's unverified summary faithfulness, except
    here the fix is whitespace normalization plus `in`. Take the free one.
    """
    return [
        claim.claim_id
        for claim in payload.claims
        if claim.evidence_ref != "none"
        and claim.evidence_quote
        and not quote_is_backed(claim.evidence_quote, texts.get(claim.evidence_ref, ""))
    ]


def check_concession(
    payload: DebateTurnPayload, turns: list[DebateTurn], side: Side
) -> str | None:
    """Concession must point at a real opposing claim, or it isn't one.
    Returns a dangling `concession_trigger` that was DROPPED, else None.

    Highest-value guardrail in the phase and it costs nothing at runtime: it
    makes "you know, that's a fair point" structurally impossible unless the
    fair point exists in the transcript and belongs to the other side. That
    part is unchanged and is the reason this check must never be relaxed
    into a keyword scan of the argument prose.

    What changed 2026-08-29: `concession_trigger` is no longer gated on
    `stance == 'concede'`. It used to be an error to name a conceded claim on
    any other stance, and the effect of that coupling was that the channel
    NEVER FIRED — across all 42 debate transcripts in the vault, 249 turns
    were `hold` or `sharpen` and not one was `concede`, so every summary the
    pipeline has ever written reported zero concessions.

    The cause was a modeling mismatch, not a weak prompt. `stance` is one
    label per TURN; a concession is about one CLAIM. The shape that actually
    occurs is partial: accept the point you cannot answer, hold the rest.
    MSFT turn 2 (2026-08-29) is the clean instance — "The bear's strongest
    point is the material weakness, and I concede that is a genuine
    overhang. But the authoritative technical relations show..." — and that
    turn is honestly labelled `hold`, because the debater IS holding. The
    old `elif` then made the truthful annotation impossible: naming the
    claim that moved you on a `hold` stance was a hard error that killed the
    turn. The only concession the schema accepted was total capitulation,
    which is not a thing a debater with a case ever does. So the concession
    went into the prose, where the Research Manager read it and cited it
    ("The bull's strongest conceded point is that the material weakness is a
    genuine overhang [turn 2]") while the transcript summary printed
    "Structurally-justified concessions: 0" about the same debate.

    Two severities, matching the two postures already in this module:

      stance='concede'  — RAISES, as before. A full concession changes what
        the transcript says the debate DID, so a trigger naming a claim
        nobody made is corruption, not a typo.
      any other stance  — DROPS AND FLAGS, like `check_rebuts`. A partial
        concession is an annotation on an otherwise sound turn; the stance,
        the argument and the claims are unaffected by a bad pointer, and
        killing a run that has already paid for fundamentals over one is the
        trade e7c82b8 and the `check_rebuts` softening both declined to make.
    """
    prior_ids = {
        claim.claim_id
        for turn in turns
        if turn.side != side
        for claim in turn.payload.claims
    }
    if payload.stance == "concede":
        if payload.concession_trigger not in prior_ids:
            raise ValueError(
                f"concede with concession_trigger="
                f"{payload.concession_trigger!r}, which is not an opposing "
                f"claim_id in this transcript (opposing ids: "
                f"{sorted(prior_ids) or 'none'})"
            )
        return None
    if payload.concession_trigger and payload.concession_trigger not in prior_ids:
        dropped = payload.concession_trigger
        payload.concession_trigger = ""
        return dropped
    return None


def check_rebuts(
    payload: DebateTurnPayload, turns: list[DebateTurn], side: Side
) -> list[str]:
    """Drop rebutted claim_ids that do not belong to a real opposing claim,
    and return the ones dropped so the caller can flag them.

    The completeness gap `check_concession` closed for `stance='concede'`:
    nothing stopped `rebuts` from naming an id that was never made, or one
    belonging to the debater's own side. A turn passing that off would look
    adversarial in the transcript while addressing nothing — the exact
    "theatre" outcome the guardrails in this module exist to rule out.

    Measured 2026-08-23 across all five termination-run transcripts before
    this check existed: 95 of 95 rebutted ids resolved to a claim made in the
    IMMEDIATELY PRECEDING turn — the strongest form of engagement, not just
    "some opposing claim somewhere." This check is deliberately looser than
    that measurement: it accepts any opposing claim so far, matching
    `check_concession`'s scope, because a later round legitimately returns to
    an earlier claim and that should not be an error. What was actually
    observed is stricter than what is enforced; recorded here so the gap
    between them is visible rather than assumed away.
    """
    opposing_ids = {
        claim.claim_id
        for turn in turns
        if turn.side != side
        for claim in turn.payload.claims
    }
    bad = [rid for rid in payload.rebuts if rid not in opposing_ids]
    if bad:
        # DROPPED, not raised. This used to raise ValueError and kill the
        # run. Live cost of that (AVGO, deepseek-v4-flash, 2026-08-29): a
        # bear turn named `technical-contained-uptrend`, an id in no
        # transcript, and took down a run that had already paid for
        # fundamentals, news and technical — $0.1586 for no memo, and no
        # `run_summary` either, since the process died before writing one.
        #
        # A dangling `rebuts` is bad debate hygiene, not a corrupted
        # artifact: the turn's argument and claims are unaffected and remain
        # perfectly usable. Removing the id keeps the transcript honest
        # (nothing downstream can resolve a reference that was never real),
        # and the flag keeps the failure visible. Same posture, and the same
        # reasoning, as e7c82b8's softening of the synthesis fabrication
        # guard: drop the trial, not the run.
        #
        # Why this arose now: the check was added after measuring 95 of 95
        # rebutted ids resolving correctly across five Haiku transcripts.
        # That is a statement about one model. A guard calibrated on one
        # model's failure modes should degrade rather than detonate when a
        # different model deviates.
        payload.rebuts = [rid for rid in payload.rebuts if rid not in bad]
    return bad


def is_productive(payload: DebateTurnPayload, turns: list[DebateTurn]) -> bool:
    """Did this turn introduce a claim_id nobody had used yet?

    OBSERVATIONAL as of 2026-08-24 — see DebateTurn.productive. Still
    computed and still recorded, because it costs nothing and it is still an
    honest reading of a turn; it just no longer feeds the router.
    """
    prior_ids = {
        claim.claim_id for turn in turns for claim in turn.payload.claims
    }
    return bool({claim.claim_id for claim in payload.claims} - prior_ids)


def check_claim_stability(payload: DebateTurnPayload, turns: list[DebateTurn]) -> list[str]:
    """claim_ids in this turn whose text disagrees with their first occurrence.

    Flags, does not raise — a model paraphrasing the same point in different
    words across turns is expected, and rejecting every wording change would
    make claim_id reuse impractical. What this catches is the case that
    matters: two turns using one id for what reads as two different
    assertions, silently, with nothing recording that it happened.

    Compares against the FIRST occurrence specifically (via `canonical_claims`
    on the transcript so far), matching the meaning `canonical_claims` fixes
    for any downstream aggregation — this check and that function agree on
    what a claim_id means, which is the whole point of having both.
    """
    first_by_id = canonical_claims(turns)
    return [
        claim.claim_id
        for claim in payload.claims
        if claim.claim_id in first_by_id
        and first_by_id[claim.claim_id].text != claim.text
    ]


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------

async def _submit(
    client: LLMClient, system_blocks: list[dict], messages: list[dict]
):
    reasoning: dict[str, Any] = {}
    if supports_adaptive_thinking(DEBATE_MODEL):
        reasoning["thinking"] = DEBATE_THINKING
        reasoning["output_config"] = {"effort": DEBATE_EFFORT}

    return await client.messages.create(
        model=DEBATE_MODEL,
        max_tokens=DEBATE_MAX_TOKENS,
        **reasoning,
        system=system_blocks,
        messages=messages,
        tools=[SUBMIT_TOOL],
        # disable_parallel_tool_use, because "call it exactly once" in the
        # prompt is not a constraint. A turn that emitted two submit_argument
        # blocks left the second unanswered on the retry path and 400'd the
        # whole node; forbidding the second call is better than handling it.
        tool_choice={
            "type": "tool",
            "name": "submit_argument",
            "disable_parallel_tool_use": True,
        },
    )



def _assert_within_budget(ticker: str, turns: list[DebateTurn], this_turn: float | None) -> None:
    total = sum(t.estimated_cost_usd or 0.0 for t in turns) + (this_turn or 0.0)
    assert_within_budget(
        total, DEBATE_BUDGET_USD,
        what="debate", context=f" for {ticker}",
        budget=f"per-debate budget after {len(turns) + 1} turn(s)",
        check="DEBATE_MODEL routing and the evidence pack size",
    )


async def run_debate_turn(
    state, side: Side, turn_index: int, client: LLMClient | None = None
) -> DebateTurn:
    """One turn: build the pack, make one forced tool call, run the guards.

    Exactly one retry on a schema violation. Retries inside a node are
    invisible to the checkpointer, so an unbounded retry loop is a runaway
    the round cap CANNOT see — it lives entirely inside one super-step. One
    retry, then raise, then resume from the checkpoint.
    """
    _maybe_crash(turn_index, "before")

    ticker = state["ticker"]
    turns: list[DebateTurn] = list(state.get("debate_turns") or [])
    texts = quotable_texts(state)
    pack = build_evidence_pack(state)
    client = client or get_client(DEBATE_MODEL)

    # Two blocks, stance first. The pack is identical across all six turns,
    # so it caches; the stance prefix differs, so bull and bear keep separate
    # caches — assumed and priced for in the phase-5 estimate.
    system_blocks = [
        {"type": "text", "text": _SYSTEM_BY_SIDE[side]},
        {
            "type": "text",
            "text": pack,
            "cache_control": {"type": "ephemeral"},
        },
    ]
    user_text = (
        f"{render_transcript(turns)}\n\n"
        f"You are the {side.upper()}. This is turn {turn_index} "
        f"(round {(turn_index // 2) + 1}). Submit your argument now."
    )
    messages: list[dict] = [{"role": "user", "content": user_text}]

    usage = UsageSummary()
    payload = await call_with_schema_retry(
        lambda msgs: _submit(client, system_blocks, msgs),
        payload_cls=DebateTurnPayload,
        tool_name="submit_argument",
        messages=messages,
        usage=usage,
        label=f"[debate] {side} turn {turn_index}",
    )

    # Structural guards, and they differ deliberately.
    #
    # `check_concession` still RAISES: a concession is a termination-shaped
    # event, so a concession trigger naming a claim nobody made changes what
    # the transcript says the debate DID, and in a checkpointed graph the
    # last good super-step survives — a loud failure costs a fix-and-resume
    # while silent corruption costs a debate you cannot trust.
    #
    # `check_rebuts` DROPS AND FLAGS: a dangling rebuts id is a bad pointer
    # inside an otherwise sound turn, and killing a run that has already paid
    # for fundamentals over one is a poor trade. See its docstring.
    #
    # `check_concession` does BOTH, split on stance: it raises on a bad
    # trigger under stance='concede' for the reason above, and drops+flags a
    # bad trigger on a partial concession (any other stance), which is the
    # same bad-pointer-in-a-sound-turn shape as `rebuts`.
    dropped_concession = check_concession(payload, turns, side)
    dropped_rebuts = check_rebuts(payload, turns, side)

    node_name = f"{side}_turn"
    event_id = new_event_id(node_name, turn_index=turn_index)
    cost = log_cost(
        ticker,
        f"trading-debate-{side}-r{(turn_index // 2) + 1}",
        usage,
        model=DEBATE_MODEL,
        run_id=state.get("run_id"),
        event_id=event_id,
    )
    _assert_within_budget(ticker, turns, cost)

    turn = DebateTurn(
        turn_index=turn_index,
        round_num=(turn_index // 2) + 1,
        side=side,
        payload=payload,
        productive=is_productive(payload, turns),
        claim_text_drift=check_claim_stability(payload, turns),
        guard_flags=unbacked_figures(
            payload.argument + "\n" + "\n".join(c.text for c in payload.claims),
            pack,
        ),
        unresolved_flags=(
            ([f"unresolved_rebuts: {', '.join(dropped_rebuts)}"] if dropped_rebuts else [])
            + ([f"unresolved_concession: {dropped_concession}"] if dropped_concession else [])
        ),
        direction_flags=contradicted_directions(
            payload.argument + "\n" + "\n".join(c.text for c in payload.claims)
        ),
        unquoted_evidence=check_quotes(payload, texts),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        estimated_cost_usd=cost,
        cost_event=record_cost_event(event_id, node_name, usage, DEBATE_MODEL, cost),
    )

    _maybe_crash(turn_index, "after")
    return turn


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------

def _format_debate_markdown(
    ticker: str, turns: list[DebateTurn], terminated_by: str
) -> str:
    total = sum(t.estimated_cost_usd or 0.0 for t in turns)
    flagged = [f for t in turns for f in t.guard_flags]
    unresolved = [u for t in turns for u in t.unresolved_flags]
    directions = [d for t in turns for d in t.direction_flags]
    unquoted = [c for t in turns for c in t.unquoted_evidence]
    drifted = sorted({cid for t in turns for cid in t.claim_text_drift})
    # Split, because the two mean different things and collapsing them is how
    # this summary came to report "0" about a debate that contained a
    # concession. A `full` concession overturns the debater's position; a
    # `partial` one accepts a specific opposing claim while holding the rest,
    # and is the only shape observed live. Both are structurally justified in
    # exactly the same sense — `check_concession` has verified the named id
    # against the opposing side's claims — so both belong in the count.
    full_concessions = [t for t in turns if t.payload.stance == "concede"]
    partial_concessions = [
        t for t in turns
        if t.payload.stance != "concede" and t.payload.concession_trigger
    ]
    concessions = full_concessions + partial_concessions

    lines = [
        f"# {ticker} — Bull/Bear Debate",
        f"**Turns:** {len(turns)} ({len(turns) // 2} full round(s))",
        f"**Terminated by:** {terminated_by or 'not recorded'}",
        f"**Model:** {DEBATE_MODEL}",
        "",
    ]

    caveats = []
    if not turns:
        caveats.append(
            "**No debate took place.** This ticker's analyst findings carry no "
            "adversarial review, which is not the same as their having survived one."
        )
    if terminated_by == "round_cap":
        caveats.append(
            f"**Truncated.** The debate hit the {len(turns) // 2}-round cap rather "
            f"than resolving — both sides still had new claims when it stopped, so "
            f"this is a truncated argument, not a concluded one."
        )
    if flagged:
        caveats.append(
            f"**{len(flagged)} figure(s) did not appear in any analyst report** and "
            f"may be fabricated: {', '.join(flagged[:10])}. Nothing downstream of "
            f"this debate re-verifies them."
        )
    if unresolved:
        caveats.append(
            f"**{len(unresolved)} turn(s) pointed at something that is not in the "
            f"transcript:** {', '.join(unresolved[:10])}."
        )
    if directions:
        caveats.append(
            f"**{len(directions)} sentence(s) state a direction their own figures "
            f"contradict:** {'; '.join(directions[:5])}. The figures are sourced; "
            f"what is said about them is not."
        )
    if unquoted:
        caveats.append(
            f"**{len(unquoted)} claim(s) cite a report but the quoted span is not "
            f"in it:** {', '.join(unquoted[:10])}."
        )
    if drifted:
        caveats.append(
            f"**{len(drifted)} claim_id(s) were reused with different wording:** "
            f"{', '.join(drifted[:10])}. A claim_id is meant to name one stable "
            f"assertion — read `canonical_claims` (the first occurrence) as the "
            f"authoritative wording, not whichever turn is read last."
        )
    if turns and not concessions:
        caveats.append(
            "**No concession was recorded structurally.** Zero here means no turn "
            "named an opposing `claim_id` in `concession_trigger` — it is NOT "
            "evidence that neither side moved. A debater who concedes a point in "
            "the argument prose without naming its id is not counted, and that has "
            "happened: MSFT 2026-08-29 turn 2 conceded the material weakness in "
            "prose on a `hold` stance, and the Research Manager went on to cite "
            "that concession while this table said zero. Read the arguments before "
            "concluding the debate was unmoved."
        )
    if caveats:
        lines += ["## Caveats", ""] + [f"- {c}" for c in caveats] + [""]

    lines += [
        "## Summary",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Turns | {len(turns)} |",
        f"| Structurally-justified concessions | {len(concessions)} "
        f"({len(full_concessions)} full, {len(partial_concessions)} partial) |",
        f"| Unproductive turns (no new claim, observational only) | "
        f"{sum(1 for t in turns if not t.productive)} |",
        f"| Flagged figures | {len(flagged)} |",
        f"| Unresolved references | {len(unresolved)} |",
        f"| Contradicted directions | {len(directions)} |",
        f"| Unverified quotes | {len(unquoted)} |",
        f"| Reused claim_ids with drifted text | {len(drifted)} |",
        f"| Estimated cost | ${total:.4f} |",
        "",
        "## Transcript",
        "",
    ]

    for turn in turns:
        lines += [
            f"### Turn {turn.turn_index} — {turn.side.upper()} (round {turn.round_num})",
            f"*stance:* `{turn.payload.stance}`"
            + (
                f" · *concedes to:* `{turn.payload.concession_trigger}`"
                + ("" if turn.payload.stance == "concede" else " (partial)")
                if turn.payload.concession_trigger
                else ""
            )
            + (f" · *rebuts:* {', '.join(turn.payload.rebuts)}" if turn.payload.rebuts else "")
            + (" · **unproductive**" if not turn.productive else ""),
            "",
            turn.payload.argument,
            "",
            "| Claim | Source | Assertion | Quote |",
            "|---|---|---|---|",
        ]
        for claim in turn.payload.claims:
            text = claim.text.replace("|", "\\|")
            quote = claim.evidence_quote.replace("|", "\\|")
            marker = " ⚠︎" if claim.claim_id in turn.claim_text_drift else ""
            lines.append(
                f"| `{claim.claim_id}`{marker} | {claim.evidence_ref} | {text} | {quote} |"
            )
        if turn.guard_flags:
            lines.append("")
            lines.append(f"*Flagged figures:* {', '.join(turn.guard_flags)}")
        if turn.unresolved_flags:
            lines.append(f"*Unresolved references:* {', '.join(turn.unresolved_flags)}")
        if turn.direction_flags:
            lines.append(f"*Contradicted direction:* {'; '.join(turn.direction_flags)}")
        if turn.unquoted_evidence:
            lines.append(f"*Unverified quotes:* {', '.join(turn.unquoted_evidence)}")
        if turn.claim_text_drift:
            lines.append(
                f"*⚠︎ Reused with different wording than the first occurrence:* "
                f"{', '.join(turn.claim_text_drift)}"
            )
        lines.append("")

    return "\n".join(lines)


def save_debate_transcript(
    ticker: str,
    turns: list[DebateTurn],
    terminated_by: str,
    provenance: str | None = None,
) -> Path:
    content = _format_debate_markdown(ticker.upper(), turns, terminated_by)
    total = sum(t.estimated_cost_usd or 0.0 for t in turns)
    return _save_output(
        content,
        ticker.upper(),
        "debate",
        cost_usd=total if turns else None,
        provenance=provenance,
        model=DEBATE_MODEL,
    )
