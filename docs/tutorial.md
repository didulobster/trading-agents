# A beginner's tour of the trading-agents project

**What this document is.** A walk through the codebase in `Documents/Code/trading-agents` as it
stands today, written for someone who has never seen it before. It covers the technology, how a
single run flows end to end, a detailed code review with real excerpts, and five things I would
change after reviewing my own read.

**How to read the code samples.** Every snippet below is copied verbatim from the repository, with
the file path given above it. Where a snippet is shortened, the cut is marked `...`. Nothing here
is pseudocode.

**A caveat before you start.** I read the source but could not execute it — the virtual environment
in `.venv/` holds macOS binaries that the sandbox I read from cannot run, so no test in this
document is a test I watched pass. Claims about *behaviour* are read off code and comments;
claims about *structure* (file layout, counts, call graphs) I verified directly.

---

## 1. What the project actually is

Two systems living in one repository, joined at one seam.

**System one — an EDGAR RAG pipeline** (`app/`, everything outside `app/agent/trading/`). It
downloads SEC filings (10-K, 10-Q, 8-K, 20-F), parses them into sections, splits them into chunks,
embeds the chunks into a Postgres vector store, and answers questions about them with citations.
"RAG" is *retrieval-augmented generation*: instead of asking a language model what it remembers
about Broadcom's cash flow, you first **retrieve** the actual paragraphs from the actual filing,
then ask the model to answer **only from those paragraphs**. The point is that every sentence in the
answer can be traced to a source document.

**System two — a multi-agent trading pipeline** (`app/agent/trading/`). It takes one ticker and one
analysis date and produces a *decision memo*: a bull case, a bear case, a risk ledger, a verdict
(buy / sell / hold / unresolved), and — importantly — a list of what the run could **not** see. It
does this by running several LLM "agents" in sequence: analysts gather evidence, a bull and a bear
argue over it, a three-person risk panel scores the risks, and a judge decides.

**The seam.** The trading pipeline's Fundamentals Analyst is not a new agent. It is a thin wrapper
that calls the EDGAR RAG research agent that already existed:

```python
# app/agent/trading/infrastructure/fundamentals_port.py
"""Wraps researcher.py's existing agent for the trading pipeline.
Deliberately calls the same path as `python -m app.agent.researcher TICKER`
(full checklist mode) — not /ask, which is a different agent behavior.
"""
```

That is the design the project set out to build, and it is the design that shipped.

**Size.** About 16,300 lines of Python under `app/`, and 612 test functions under `tests/`, of which
464 sit under `tests/agent/trading/`. The largest single file is
`app/agent/trading/infrastructure/debate_port.py` at 1,615 lines — which tells you something true
about the project: most of the code is not "call the model", it is **checking what the model said**.

---

## 2. The technology, explained

| Layer | Choice | What it is, and why it is here |
|---|---|---|
| Language | Python 3.13 | Required minimum in `pyproject.toml`. |
| Package manager | `uv` | Lockfile-driven installs; `uv.lock` is committed. |
| Agent orchestration | **LangGraph** ≥1.0 | The framework that runs the multi-agent pipeline. Explained below. |
| State persistence | `langgraph-checkpoint-postgres` | Saves the run's state to Postgres after every step, so a crashed run resumes instead of restarting. |
| Database | PostgreSQL + **pgvector** | One store for both ordinary tables and the embedding vectors. |
| DB driver | `psycopg` 3 + pool | Async SQL, no ORM. |
| Migrations | Alembic | Versioned schema changes under `migrations/`. |
| API | FastAPI + Uvicorn | The RAG side is an HTTP service (`app/main.py`); the agent's tools call it over HTTP. |
| LLM access | `anthropic`, `openai` SDKs behind `app/infrastructure/llm/` | Provider is chosen by model-id prefix, so a role can be swapped by editing one env var. |
| Embeddings | OpenAI `text-embedding-3-small` | Turns a chunk of text into a 1536-number vector. |
| Filing parsing | BeautifulSoup4 + lxml, custom parser | `edgartools` was dropped for breaking API changes. |
| Market data | `yfinance`, `finnhub-python` | Price history and company news. |
| Indicators | `pandas-ta-classic` | SMA, RSI, MACD, Bollinger bands. |
| Validation | **Pydantic** v2 | Every message between Python and an LLM is a typed model. |
| Tests | pytest | 612 test functions. |

### The three ideas you need before reading the code

**1. A graph, not a script.** LangGraph models a workflow as a *graph*: **nodes** are functions,
**edges** say which node runs next, and a shared **state** object is threaded through all of them. A
node does not return the whole state — it returns a small dictionary of the fields it changed, and
LangGraph merges that in. Some fields overwrite; some *accumulate*. That distinction matters a lot
here (see §4.2).

**2. Checkpointing and super-steps.** After each node execution — LangGraph calls one such execution
a *super-step* — the entire state is serialised to Postgres. If the process dies, a rerun with the
same `thread_id` picks up exactly where it stopped. This is why the debate is written as *one node
per turn* rather than a loop inside one node:

```python
# app/agent/trading/application/debate_nodes.py
    for r in range(rounds) inside a single debate node -> 1 checkpoint, at
        node exit. A kill mid-round-2 resumes at turn 0 and the whole debate
        is lost.
    one node per turn, cycled                          -> 2 x rounds
        checkpoints. A kill resumes at the exact turn in flight.
```

**3. Ports and adapters (hexagonal architecture).** Each agent area is split three ways:

- `domain/` — plain Pydantic types and pure rules. No network, no LLM, no clock.
- `application/` — the nodes and routers. Orchestration logic.
- `infrastructure/` — the "ports": the code that actually talks to an LLM, a vendor API, or disk.

The payoff is testability. A *pure* function — same inputs, same outputs, no I/O — can be tested
exhaustively in milliseconds for zero API cost. The project leans on this hard, and says so:

```python
# app/agent/trading/application/debate_router.py
A pure function of state — no I/O, no LLM, no clock. That is what makes it
exhaustively testable: `next_debate_step` can be evaluated over every
reachable input in milliseconds at zero API cost, which is a proof of
termination rather than a sample of it.
```

---

## 3. High-level walkthrough: one run, start to finish

You start a run like this:

```
python -m app.agent.trading.interface.cli AVGO --as-of 2026-08-29 --max-usd 0.75
```

Here is what happens.

```
                    START
                      │
        ┌─────────────▼─────────────┐
        │  ANALYSTS (run in order)  │
        │  fundamentals ─ EDGAR RAG │
        │  technical    ─ prices    │
        │  news → sentiment         │
        └─────────────┬─────────────┘
                      │  conditional edge
        ┌─────────────▼─────────────┐
        │  DEBATE  (cycle)          │   bull ⇄ bear, 3 rounds = 6 turns
        └─────────────┬─────────────┘
                 debate_close        ← records WHY it stopped
                      │
        ┌─────────────▼─────────────┐
        │  RISK PANEL (cycle)       │   neutral → aggressive → conservative,
        └─────────────┬─────────────┘   3 rounds = 9 turns
                  risk_close        ← records WHY it stopped
                      │
        ┌─────────────▼─────────────┐
        │  SYNTHESIZER              │   Research Manager + Risk Judge,
        └─────────────┬─────────────┘   run 3 times, majority vote
                     END

   every edge above also has an "abort" branch → graceful_abort (budget/deadline)
```

**Stage 1 — Analysts.** Three legs, run in a fixed order.

- *Fundamentals* hands the ticker to the EDGAR research agent, which runs a forensic checklist by
  making up to 30 `ask_edgar` retrieval calls against the filing corpus and writes a memo.
- *Technical* fetches OHLCV price bars bounded at the analysis date, computes indicators in pure
  Python, then asks an LLM to interpret them — and checks every number in that interpretation
  against the computed values.
- *News* pulls vendor articles in a window ending at the analysis date, sanitises them, has an LLM
  summarise and label each one, then a **non-LLM** node counts the labels into a sentiment score.

**Stage 2 — Debate.** A bull agent and a bear agent alternate for three rounds. Each turn produces
structured *claims*, each claim citing which analyst report it came from and quoting a span from it.
Python then checks the quote is really in that report, and that every number in the turn appears in
the evidence pack.

**Stage 3 — Risk panel.** Three personas — neutral, aggressive, conservative — rotate for three
rounds. Round one enumerates and scores risk factors 1–5 on severity and likelihood; later rounds
re-adjudicate the contested ones. Python assembles the results into a **ledger**: one row per risk
factor, each persona's score, and where they disagree.

**Stage 4 — Synthesis.** A *Research Manager* writes the bull and bear cases from the debate only. A
*Risk Judge* reads the ledger plus that thesis and issues the verdict. This pair runs **three
times** over independently sampled risk panels, and the memo's verdict is the majority. No majority
means the verdict is reported as `unresolved` rather than picking one.

**Throughout — the ledger of what was *not* seen.** Every stage records its own blind spots, and
they all land in the memo's `data_gaps`. This is the project's governing idea: a memo that hit a
round cap must not read like a memo that resolved.

**Output.** Markdown artifacts in a dated vault folder (fundamentals memo, technical report,
sentiment report, debate transcript, risk transcript, decision memo), a JSON memo on stdout, and
one `run_summary` line appended to `docs/cost-log.jsonl`.

---

## 4. Detailed code review

### 4.1 The graph is built, not written out

`build_trading_graph` assembles nodes and edges from data rather than listing them one by one. That
is what lets `--only news` produce a valid smaller graph.

```python
# app/agent/trading/infrastructure/graph.py
ANALYST_CHAINS = {
    "fundamentals": (("fundamentals", fundamentals_node),),
    "technical": (("technical", technical_node),),
    "news": (("news", news_node), ("sentiment", sentiment_node)),
}
ALL_ANALYSTS = tuple(ANALYST_CHAINS)
```

Note `news` is two nodes. The sentiment aggregation reads the news digest and nothing else, so it
is never independently selectable — encoding that as a *chain* rather than a separate entry makes
the invalid combination unrepresentable.

Selection order is deliberately ignored:

```python
    selected = (
        ALL_ANALYSTS
        if analysts is None
        else tuple(a for a in ALL_ANALYSTS if a in set(analysts))
    )
```

`--only news --only technical` and `--only technical --only news` build the identical graph. A
subset run is always a strict subsequence of the full run.

**Review.** This is the right shape. One thing to notice as a reader: `analysts` is validated with
a helpful error, but the two failure cases (`unknown analyst`, `empty selection`) both raise
`ValueError` out of a builder that the CLI calls without a try/except, so the user sees a traceback
rather than a message. Minor, and the `argparse` `choices=ALL_ANALYSTS` already catches the common
case upstream.

### 4.2 State: which channels accumulate, and why

`TradingState` is a `TypedDict`. Most fields overwrite. Three do not:

```python
# app/agent/trading/domain/trading_state.py
    debate_turns: Annotated[list[DebateTurn], operator.add]
```

`Annotated[..., operator.add]` tells LangGraph: when a node returns this field, **concatenate** it
with what is already there. This is required because the debate is a cycle — a plain overwrite
channel would keep only the last turn. The consequence, spelled out in the code, is a rule nodes
must obey:

```python
    # A DELTA, never the accumulated list. `operator.add` concatenates, so
    # returning the whole list doubles it every super-step — and that failure
    # looks exactly like the runaway loop this phase exists to bound.
    events = [turn.cost_event] if turn.cost_event else []
    return {"debate_turns": [turn], "cost_events": events}
```

There is also a deliberate *absence*: no round counter.

```python
    # There is deliberately no separate round counter: round state IS
    # len(debate_turns). A counter beside the list is a second source of
    # truth that can desync, and a desync shows up as either an early stop or
    # a runaway — both silent.
```

**Review.** "Derive, don't store" is applied consistently — the risk ledger is likewise a pure
function of `risk_turns` and is explicitly kept out of state. The comments even record that
`operator.add`'s crash-safety was an *assumption* until it was tested by killing a live run with
`os._exit(1)` and resuming. That is the right way to hold a belief about a distributed system.

### 4.3 Termination: three independent layers

The single largest risk in an agent loop is that it never stops. This code answers it three times
over, and says so:

```python
# app/agent/trading/application/debate_router.py
  1. `n >= MAX_TURNS` here                       — normal operation
  2. `recursion_limit` in the CLI invoke config  — a router bug
  3. runtime asserts at node entry               — a wiring bug that
     (see application/debate_nodes.py)             bypassed the router
```

Layer 1 is a pure function:

```python
MAX_ROUNDS = 3
MAX_TURNS = 2 * MAX_ROUNDS


def next_debate_step(state) -> str:
    turns = state.get("debate_turns") or []
    n = len(turns)

    # The hard cap. First, unconditional, and it cannot raise.
    if n >= MAX_TURNS:
        return "done"

    # No evidence -> no debate. A `--only` run that excluded every analyst leg
    # would otherwise produce a debate over an empty pack: two models arguing
    # from nothing, which reads like a debate and is theatre.
    if n == 0 and all(state.get(key) is None for key in ANALYST_OUTPUTS.values()):
        return "done"

    return "bull" if n % 2 == 0 else "bear"
```

Layer 2 is a derived global budget — every term computed, no literals:

```python
# app/agent/trading/interface/cli.py
_FIXED_NODES = sum(len(chain) for chain in ANALYST_CHAINS.values())
_FIXED_NODES += 4   # debate_close, risk_close, synthesizer, graceful_abort
RECURSION_LIMIT = (
    2 * MAX_ROUNDS            # debate turns (bull/bear alternation)
    + 3 * RISK_MAX_ROUNDS     # risk turns (three-persona rotation)
    + _FIXED_NODES
    + 5                       # headroom
)
```

With the current constants that is 6 + 9 + 8 + 5 = 28 super-steps. Raise `MAX_ROUNDS` and the limit
follows automatically.

Layer 3 sits at node entry, and the *contiguity* check is the subtle one:

```python
# app/agent/trading/application/debate_nodes.py
    indices = [t.turn_index for t in turns]
    if indices != list(range(turn_index)):
        raise RuntimeError(
            f"debate_turns indices are {indices}, expected "
            f"{list(range(turn_index))} — the add-reducer double-applied on "
            f"resume, or a turn was lost. ..."
        )
```

Checking "is this index already taken?" would miss `[0, 1, 2, 2]`, whose length is 4 — the run would
sail past the cap looking clean. Checking `indices == range(n)` catches it.

**Review.** This is the strongest part of the codebase. Note also what was *removed*: an
"unproductive debate" early-stop that never fired in five full runs was deleted, with the reasoning
recorded — *"A dead branch inside a termination guard is worse than no branch: it reads as a second
safety layer that is not there."* Deleting a comforting-but-inert safety check takes discipline.

### 4.4 Guards: the model produces content, Python owns the facts

The recurring rule across `domain/risk.py`, `domain/debate.py` and the ports is that the model
writes prose and Python owns every identifier, counter and label.

```python
# app/agent/trading/domain/risk.py
class RiskFactor(BaseModel):
    """A candidate risk. Proposed by the LLM as text; `factor_id` is
    Python-assigned in `risk_port._assemble` — never trust one on the wire."""
```

Numbers are then checked by **containment**, not tolerance:

```python
# app/agent/trading/infrastructure/debate_port.py
def _flag_debate_numbers(text: str, evidence_pack: str) -> list[str]:
    """Every figure in a debate turn must appear verbatim in the evidence pack.

    Containment rather than the Phase 3 tolerance match, and the difference
    matters. ... Scrape every number out of a fundamentals
    memo and there are a hundred-plus known values carrying the same bands;
    in dense regions those bands overlap and cover most of the number line, a
    fabricated figure lands inside somebody's band, and the guard returns []
    forever while reading as clean.
    """
```

That is a genuinely good piece of reasoning: a ±2% tolerance check *degrades as the corpus grows*,
silently, while looking like it works. Three faithful-restatement exemptions were then added, each
because a real run produced a false positive — rounding (`41.2` for `41.2033`, cleared at the
figure's own precision, not by a tolerance band), percent transforms, and sign/magnitude.

Quote checking normalises both sides before comparing:

```python
_QUOTE_NOISE = re.compile(r'[\s"\u201c\u201d\u2018\u2019\'*_`]+')


def _norm(text: str) -> str:
    return _QUOTE_NOISE.sub("", text).lower()


def check_quotes(payload: DebateTurnPayload, texts: dict[str, str]) -> list[str]:
    """claim_ids whose evidence_quote is not actually in the report it names."""
    return [
        claim.claim_id
        for claim in payload.claims
        if claim.evidence_ref != "none"
        and claim.evidence_quote
        and _norm(claim.evidence_quote) not in _norm(texts.get(claim.evidence_ref, ""))
    ]
```

Stripping markdown emphasis from both sides is safe by construction — the markers cannot make a
false quote match a real span, they can only stop formatting from deciding the answer.

**The critical posture:** guards *flag*, they do not *block*.

```python
# app/agent/trading/domain/sanitize.py
A hit never drops the article — a real article that happens to quote a
prompt-injection news story would otherwise be silently censored, which is
its own correctness bug (same posture as every other guard in this
pipeline: flag, don't silently absorb).
```

**Review.** The guard layer is where most of the engineering went, and it is well-judged. One
observation: every guard is a regex or containment check over text, which means each is a *heuristic
with a false-positive class*, and the code is honest about that. The risk is cumulative — a memo
carrying eight guard categories in `data_gaps` is hard for a human to read. There is already
evidence of this being managed (`unexpected_missing_scores` exists precisely because the ledger was
reporting the panel's protocol-required silence as a defect in every run of a five-run battery).

### 4.5 Prompt-injection defence at the one untrusted seam

News articles are the only attacker-writable input, and the threat model is stated plainly:

```python
# app/agent/trading/domain/sanitize.py
Threat model: an article's text is attacker-writable (anyone can publish a
news story, and a vendor feed will carry it), and the debate/synthesis
agents must treat it as EVIDENCE to reason about, never as INSTRUCTIONS to
follow. Regex cannot catch semantic injection — a well-written paragraph can
steer a model without using any of the phrasing below — so this is a
layered, flag-not-assert defense, not a guarantee: structural delimiting
... is the primary defense; the pattern screen here is a second, weaker
layer whose only job is to make an obvious attempt VISIBLE, not to block it.
```

The invisible-character strip is the part most implementations forget:

```python
_KEEP_CONTROL = {"\n", "\t", "\r"}


def _strip_invisible(text: str) -> str:
    return "".join(
        ch
        for ch in text
        if ch in _KEEP_CONTROL
        or unicodedata.category(ch) not in ("Cf", "Cc")
    )
```

Unicode categories `Cf` and `Cc` cover zero-width spaces, joiners and bidirectional overrides — text
a human reviewer cannot see but a model reads. There is a canary test for this
(`tests/agent/trading/test_injection_canary.py`) with paired canary and control fixtures.

**Review.** Correctly scoped and correctly humble. Naming the primary defence (structural delimiting
plus a framing instruction in the cached system prompt) and calling the regex the weaker second
layer is exactly right; most projects invert that and trust the regex.

### 4.6 Lookahead protection — and one leg that is missing it

For a system that analyses a *historical* date, the worst silent bug is using data that did not
exist yet. Three nodes refuse to run without an explicit bound:

```python
# app/agent/trading/application/nodes.py
async def news_node(state: TradingState) -> dict:
    ticker = state["ticker"]
    as_of = state.get("as_of_date")
    if as_of is None:
        # Fail loud rather than defaulting to today: a silent
        # `or date.today()` fallback is precisely how lookahead
        # contamination gets into a backtest.
        raise ValueError(
            "as_of_date missing from TradingState — refusing to run unbounded. "
            "A news fetch without an explicit upper bound is a lookahead bug."
        )
```

And there is a belt-and-braces post-assertion after the digest is built:

```python
    late = [i for i in digest.items if i.published_date > as_of]
    if late:
        raise AssertionError(
            f"Lookahead leak: {len(late)} article(s) dated after {as_of} "
            f"reached the digest — first: {late[0].published_date}"
        )
```

`date.today()` appears exactly once in the trading CLI, at the argument parser, with a comment
saying so. That is the discipline.

**But the fundamentals leg does not participate.** `fundamentals_node` never passes the analysis
date down:

```python
# app/agent/trading/application/nodes.py
async def fundamentals_node(state: TradingState) -> dict:
    print(f"[fundamentals] running for {state['ticker']}")
    report = await get_fundamentals_report(state["ticker"], run_id=state.get("run_id"))
```

and the port reads the wall clock itself:

```python
# app/agent/trading/infrastructure/fundamentals_port.py
async def get_fundamentals_report(
    ticker: str, run_id: str | None = None
) -> FundamentalsReport:
    ...
    today = date.today()
    task = f"Today's date is {today.isoformat()}. Run the full research checklist for {ticker}."
```

So `--as-of 2026-03-01` bounds news and prices to March, and tells the fundamentals agent that today
is whatever today actually is. See §5.1.

### 4.7 Cost control, and where it stops

Budget and deadline are set once, at the CLI boundary, and never recomputed:

```python
# app/agent/trading/domain/budget.py
class RunBudget(BaseModel):
    """Set once per run, at the CLI boundary. Never mutated."""

    max_usd: float
    deadline_utc: datetime  # start_time + wall_clock_timeout, computed once
```

The check itself is pure and clock-injected, so a boundary case can be constructed deterministically
in a test:

```python
# app/agent/trading/application/guards.py
def check_run_guards(
    events: list[CostEvent], budget: RunBudget, now: datetime
) -> RunTermination | None:
    if total_spend(events) >= budget.max_usd:
        return RunTermination.BUDGET_EXCEEDED
    if now >= budget.deadline_utc:
        return RunTermination.DEADLINE_EXCEEDED
    return None
```

It is wired in by wrapping *every* router with a guard, so a breach is reachable from anywhere:

```python
# app/agent/trading/infrastructure/graph.py
def _guarded(inner):
    route = inner if callable(inner) else (lambda state: inner)

    def router(state):
        budget = state.get("budget")
        if budget is not None:
            events = state.get("cost_events") or []
            if check_run_guards(events, budget, datetime.now(timezone.utc)) is not None:
                return "abort"
        return route(state)

    return router
```

Deduplication lives in the *reader*, not the reducer, so a crash-resume that re-appends a pending
write still totals correctly and the duplicate is surfaced as a warning rather than silently fixed:

```python
# app/agent/trading/domain/budget.py
def total_spend(events: list[CostEvent]) -> float:
    seen: set[str] = set()
    total = 0.0
    for event in events:
        if event.event_id in seen:
            logger.warning(
                "duplicate cost event %s for node %s — resume likely "
                "re-appended a pending write; counted once", ...
            )
            continue
        seen.add(event.event_id)
        total += event.usd
    return total
```

There is also a nicely-earned CLI refusal, added after a real incident:

```python
# app/agent/trading/interface/cli.py
            # Live cost of that hole (MSFT, 2026-08-28): a thread whose first
            # attempt died ~17 hours earlier was resumed with --max-usd 1.40.
            # The run silently used the checkpointed 1.10, executed the whole
            # fundamentals stage, then aborted `deadline_exceeded` on the
            # first guard check after it — $0.4069 spent, no memo.
```

**Review.** Well-built, with one real gap and one documentation mismatch — both in §5.

### 4.8 The synthesizer: sampling instead of pretending

The most interesting decision in the project is here. Measurement showed the Risk Judge's verdict
genuinely split across independent samples of the *same* fixed debate — and that the variance lived
in the panel, not the judge:

```python
# app/agent/trading/application/nodes.py
# A fixed-ledger repeat of the Risk Judge alone (3 calls against one frozen
# ledger, AVGO) came back unanimous, which localizes the variance to the
# PANEL, not the Judge — so sampling has to re-run the whole (panel,
# Research Manager, Risk Judge) trial, not just resample the Judge's call.
RISK_VERDICT_SAMPLES = 3
```

So the node runs three whole trials, drops any trial the fabrication guard rejects, and votes:

```python
    verdicts = [m.verdict.value for m in memos]
    top_verdict, top_count = Counter(verdicts).most_common(1)[0]
    has_majority = top_count > len(memos) / 2

    if has_majority:
        # Reuse the first sample whose OWN verdict agrees with the
        # majority, so the memo's narrative and its verdict label are
        # never inconsistent with each other ...
        final_idx = next(i for i, m in enumerate(memos) if m.verdict.value == top_verdict)
```

Three details worth pointing at:

1. **`unresolved` is a Python-computed outcome, not a model option.** The tool schema offered to the
   model is `IndividualVerdict` (buy/sell/hold only); `Verdict` adds `UNRESOLVED`, which only the
   vote can produce. No single call gets to declare non-resolution.
2. **The winning memo's narrative and label must agree** — picking sample 1's prose and sample 2's
   verdict would produce a memo arguing sell and labelled hold.
3. **A dropped trial's cost is still counted.** `all_cost_events` collects spend from trials whose
   memo never survived, because *"undercounting a run's real spend is exactly the failure mode the
   run-level budget guard exists to prevent."*

And the naming fix that best captures the project's temperament:

```python
# app/agent/trading/domain/decision_memo.py
class EvidenceQuality(BaseModel):
    """What this run had to work with — NOT how likely the verdict is right.

    Renamed from `confidence` on 2026-08-29, because that name promised a
    probability and delivered an input-quality measure. `score` is
    `0.6*analyst_coverage + 0.3*(1 - panel_dispersion) + 0.1*(1 - guard_flags/10)`,
    so on any full run `analyst_coverage` is 1.0 and **0.6 of the number is
    a constant** ...
    """
```

It reported 0.97 on a 2-1 verdict split against 0.94 on a unanimous one. The fix was not to
recalibrate the number but to **rename it to what it actually measures** and add a separate
`verdict_agreement` field for the question readers were really asking.

### 4.9 Checkpoint safety

Deserialising arbitrary Python from a database is a code-execution risk, so the checkpointer passes
an explicit allowlist:

```python
# app/agent/trading/infrastructure/checkpointer.py
ALLOWED_MSGPACK_MODULES = [
    ("app.agent.trading.domain.decision_memo", "Verdict"),
    ...
    # Phase 5. Three entries for one channel because DebateTurn nests
    # DebateTurnPayload nests DebateClaim, and an unregistered type fails on
    # DESERIALIZATION ONLY — a live run stays green and the resume goes red,
    # which is the worst possible place to discover a missing line.
```

And — I checked, expecting to find this missing — the completeness of that list is enforced by a
test that walks `TradingState`'s annotations:
`test_every_domain_type_reachable_from_trading_state_is_registered`. The nodes additionally check
for stale checkpoints and give a real instruction rather than an `AttributeError` three frames on:

```python
# app/agent/trading/application/debate_nodes.py
    stale = [t for t in turns if not isinstance(t, DebateTurn)]
    if stale:
        raise TypeError(
            f"... this checkpoint predates a debate schema change and cannot be "
            f"resumed. Re-run the ticker under a new --thread-id."
        )
```

### 4.10 One small thing worth copying

Field order in a structured-output schema is load-bearing:

```python
# app/agent/trading/domain/risk.py
    Field order is deliberate, not alphabetical or "natural": `proposes`
    and `scores` come BEFORE `argument`. Strict structured output fills
    fields in schema-declaration order, autoregressively — with `argument`
    first (as this was originally written), every score is sampled
    CONDITIONED ON ~180 freshly-generated words of prose ...
```

Moving `argument` last means the numbers are sampled first and the prose becomes a summary of an
already-fixed answer. That is a real property of autoregressive models that almost nobody accounts
for in schema design.

---

## 5. Five improvements, from reviewing my own read

Ordered by how much a mistake there would cost.

### 5.1 Thread `as_of_date` into the fundamentals leg — it is the one lookahead hole left

**What I found.** `technical_node`, `news_node` and `synthesizer_node` each *raise* if `as_of_date`
is missing, and `news_node` adds a post-assertion that no article is dated after it. The
fundamentals leg does neither: `fundamentals_node` calls
`get_fundamentals_report(state["ticker"], run_id=...)` with no date, and the port does
`today = date.today()` and puts that date in the agent's task prompt. The EDGAR agent then chooses
which filings to query with today's date in hand.

**Why it matters.** It is exactly the failure the other three nodes were hardened against, in the
one leg that reads the most data. A historical probe at `--as-of 2026-03-01` produces a memo whose
news and prices are bounded at March and whose fundamentals research is not. Worse, it fails
*quietly* — the memo looks complete.

**Suggested fix.** Add a required `as_of: date` parameter to `get_fundamentals_report`, pass
`state["as_of_date"]`, use it in the task string, and push it into the `ask_edgar` tool as a
`filed_before` filter so retrieval itself is bounded. Mirror the existing pattern: raise rather than
default.

### 5.2 Check the budget *inside* the synthesizer's sampling loop

**What I found.** `guards.py` documents the overshoot bound as one call:

> *"Ordering means a run can overshoot `max_usd` by at most one call's cost — the check runs BEFORE
> the next call, not after."*

But guards run on *edges*, and `synthesizer_node` is one node that makes many calls. With
`RISK_VERDICT_SAMPLES = 3`: trials 2 and 3 each run a fresh nine-turn risk panel via
`_sample_additional_risk_panel` (18 LLM calls), and each of the three trials runs `run_synthesis`,
which is a Research Manager call plus a Risk Judge call (6 more). That is **at least 24 model calls
between two budget checks**, before retries.

**Why it matters.** The stated bound is wrong by more than an order of magnitude for the most
expensive node in the pipeline, and the fix is cheap. It is also the kind of error that only shows
up on the bill.

**Suggested fix.** Call `check_run_guards` at the top of each sampling iteration (and between panel
turns inside `_sample_additional_risk_panel`), and on a breach stop sampling and vote on the trials
already completed — that degrades to a weaker signal, which the memo already knows how to report
via the existing `dropped` gap text. Then correct the docstring in `guards.py` to say the bound is
one *node*, not one *call*.

### 5.3 Make the fundamentals cache honest about what it keys on

**What I found.**

```python
_CACHE_DIR = Path(__file__).resolve().parents[1] / ".fundamentals_cache"
_USE_MOCK = os.getenv("MOCK_FUNDAMENTALS", "").strip() == "1"


def _cache_path(ticker: str) -> Path:
    return _CACHE_DIR / f"{ticker.upper()}.json"
```

The cache is **written on every real run** but **read only when `MOCK_FUNDAMENTALS=1`**, and the key
is the ticker alone — no analysis date, no model, no prompt version. On a cache hit it prints the
report's age and returns it regardless.

**Why it matters.** It is a correctness trap sitting one environment variable away from a real run.
A developer setting `MOCK_FUNDAMENTALS=1` to iterate on the debate cheaply can silently pair an
August fundamentals memo with a March analysis date — and combined with 5.1 there is nothing in the
system that would notice. The seven `.json` files currently in `.fundamentals_cache/` are exactly
this shape.

**Suggested fix.** Key on `(ticker, as_of, model)`, and either refuse a hit whose `as_of` differs
from the run's or record the mismatch as a `data_gap` on the memo. If the cache is meant only as a
dev convenience, gate the *write* behind the same env var as the read, so a production run does not
leave loaded weapons on disk.

### 5.4 `_describe_stale_budget` accepts a parameter it never uses

**What I found.**

```python
def _describe_stale_budget(values: dict, max_usd: float, wall_clock_timeout_s: float) -> str | None:
```

The body reads `budget.deadline_utc` and `budget.max_usd`, and warns when `--max-usd` disagrees with
the inherited value. `wall_clock_timeout_s` is never referenced.

**Why it matters.** Small, but it is a *silent asymmetry* in exactly the function that exists to
stop silent asymmetries. A user who resumes with `--wall-clock-timeout-s 7200` gets a clear note
that `--max-usd` was ignored and no note at all that their timeout was — even though the timeout is
the flag more likely to be raised on a resume, and the one the MSFT incident in the comment above
was actually about.

**Suggested fix.** Emit the same "IGNORED on a resume" note when the requested timeout would produce
a deadline different from the inherited one; or drop the parameter. Either is fine — having it
present and unread is the one option that misleads.

### 5.5 Give the repository a front door: README, `.env.example`, and CI

**What I found.** There is no README and no CI configuration. `architecture.md` (42 KB) and
`trading-agent-known-gaps.md` (168 KB, 32 dated sections) are excellent, but they are *engineering
journals*, not entry points — neither tells a newcomer how to get a run to work. Meanwhile several
environment variables are hard requirements read at *import* time:

```python
# app/agent/researcher.py
MAX_TURNS = int(os.environ["LOOP_MAX_TURNS"])
...
MEMO_DIR = Path.home() / os.environ["MEMO_DIR"]
```

`researcher.py` is imported by `fundamentals_port` → `nodes` → `graph`, so a missing `LOOP_MAX_TURNS`
fails the *entire trading CLI* at import with a bare `KeyError: 'LOOP_MAX_TURNS'` — before argument
parsing, with no indication of which file or what value is expected. `.env` is correctly gitignored,
which means nothing in the repository lists what it must contain.

**Why it matters.** 612 tests exist and nothing runs them automatically; the project's whole method
is "measure, then decide", and the measuring is manual. And the first experience of a new machine
(or a future you) is a `KeyError` on a variable name that appears in no documentation.

**Suggested fix.** Three small things: a `README.md` with the prerequisites, the Postgres/pgvector
setup, one ingest command and one trading command; a committed `.env.example` listing every variable
with a comment (the real `.env` already has excellent comments — copy them, drop the secrets); and a
GitHub Actions workflow running `uv run pytest`. Then convert those two `os.environ[...]` reads into
a validated settings object that fails with a message naming the variable and its purpose.

---

## 6. Reading order, if you are starting tomorrow

1. `app/agent/trading/domain/trading_state.py` — what a run *is*.
2. `app/agent/trading/infrastructure/graph.py` — how the pieces connect.
3. `app/agent/trading/application/debate_router.py` — the smallest complete example of the project's
   philosophy: pure, exhaustively tested, one termination lever, dead branches deleted.
4. `app/agent/trading/application/nodes.py` — the caveat functions, which are where the memo's
   honesty actually comes from.
5. `app/agent/trading/infrastructure/debate_port.py` — the guards. Long, but it is where the
   hard-won knowledge lives.
6. `trading-agent-known-gaps.md` — read the dated section for whatever you are about to change.
   Most surprises in this codebase have already been surprising once and were written down.
