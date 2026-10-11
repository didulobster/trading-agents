# Shared kernel

Plumbing that both [EDGAR Research](../edgar_research/CONTEXT.md) and Trading use and neither owns: LLM providers, pricing, cost logging, config and the vault. See [CONTEXT-MAP.md](../../CONTEXT-MAP.md).

## Provider abstraction (`app/infrastructure/llm/`)

Every LLM client in the app is built by `get_client(model)`. Which provider
serves a call is decided by the model id's prefix — `claude-*` to Anthropic,
`deepseek*` to DeepSeek, `gpt-*`/`o1`/`o3`/`o4` to OpenAI — so a run can mix
providers per role without a global switch. `LLM_PROVIDER` overrides that
inference wholesale for a gateway whose model ids carry no useful prefix.

### Role configuration

Ten LLM roles, each with its own `.env` variable, all falling back to
`LLM_CLAUDE_MODEL`:

| Role | Variable |
| --- | --- |
| research agent loop, and the fundamentals node that runs it | `LLM_CLAUDE_MODEL` |
| answer generation behind `POST /ask` | `LLM_ANSWER_MODEL` |
| query decomposition | `LLM_DECOMPOSER_MODEL` |
| financial-metric extraction | `LLM_EXTRACTION_MODEL` |
| news digest | `TRADING_NEWS_DIGEST_MODEL` |
| technical-indicator interpretation | `TRADING_TECHNICAL_MODEL` |
| bull/bear debate turns | `TRADING_DEBATE_MODEL` |
| risk panel personas | `TRADING_RISK_MODEL` |
| research manager synthesis | `TRADING_RESEARCH_MANAGER_MODEL` |
| risk judge, final verdict | `TRADING_RISK_JUDGE_MODEL` |

`LLM_CLAUDE_MODEL` is the only required one, so a project that sets nothing
else behaves exactly as it did when that was the only knob. Five of these
roles previously had no variable at all and were pinned to it; two more
(`RISK_MODEL`, `RISK_JUDGE_MODEL`) sat in `.env` and were read by nothing,
so changing them looked like it worked. `scripts/run_p9_battery.py` records
`model_env_vars()` with each run rather than a hand-maintained copy — the
copy had drifted, and a run recorded against the wrong list is one whose
configuration cannot be reconstructed.

**Anthropic's message shape is the internal lingua franca.** The ports build
`tool_use`/`tool_result` turns by hand, the synthesis and debate schema
retries re-send `response.content` verbatim, and the provenance guards read
block text — that shape is load-bearing in tested code, so it stayed, and
translation happens at the wire instead. `OpenAICompatClient` duck-types
`AsyncAnthropic` for the surface this repo uses (`messages.create` returning
`.content` / `.stop_reason` / `.usage`) and maps it onto an OpenAI-dialect
chat-completions endpoint.

What does not survive that translation, dropped with a once-per-process
warning: `cache_control` breakpoints (DeepSeek caches automatically and has
no equivalent to place), `betas`, `top_k` and `metadata`. `strict: true` on
a tool schema DOES carry over — the dialect supports it, and it matters:
`strict` was added to `SUBMIT_TOOL` because 3 of 3 live debate turns came
back with a flattened payload without it.

**Thinking is on by default on DeepSeek, and it rejects a constrained
`tool_choice`.** Both `required` and a named function come back
`400 "Thinking mode does not support this tool_choice"`; only `auto`
survives. Since the debate, risk and synthesis ports all force a named tool
— their contract is "call exactly this tool, exactly once", and `_extract`
raises when no tool block arrives — the shim sends
`thinking: {"type": "disabled"}` on any call that constrains the choice, and
translates Anthropic's `thinking`/`output_config` to the provider's
`thinking` object otherwise. Forcing the tool wins over keeping thinking:
`auto` would trade a hard API guarantee for a behavioural hope on exactly
the calls whose output is most load-bearing. Reasoning tokens bill as
output either way, so no cost accounting depends on the choice. The
parameter goes out in `extra_body` — the OpenAI SDK raises `TypeError` on
top-level kwargs it does not recognise.

`max_tokens` is clamped to the provider's ceiling, which surfaces as
`stop_reason=max_tokens` on genuinely long output rather than as a 400. Both
V4 models top out at 384K against the research agent's 16000, so it does not
fire today — it is carried because the retired `deepseek-chat` capped at
8192, where an unclamped request would have failed on the final turn of a
run already paid for.

Cost config moved to `llm/pricing.py` and is re-exported from `researcher.py`
as `_MODEL_PRICING`. `LLM_PRICING_OVERRIDES` (JSON, env) merges over it, so
a repriced model is a config change rather than a code change — and a
malformed override raises at import rather than leaving a stale rate in
place, because an unpriced or mispriced model makes the per-run budget
assertion silently unable to fire.

For DeepSeek, `input_tokens` is the *cache-miss* count, not `prompt_tokens`:
their `prompt_tokens` is hits plus misses, and pricing it as input while also
counting hits as `cache_read` would overstate every cached run.

**DeepSeek prices by time of day and the table does not.** Off-peak rates are
half of peak, and off-peak is every hour outside 01:00-04:00 and 06:00-10:00
UTC Monday-Friday — so most runs cost about half what `pricing.py` says. The
table holds the peak rate deliberately, the same call made for Sonnet 5's
introductory pricing: over-estimating fails safe, whereas tracking whichever
rate applies right now turns "did this run exceed its cap" into a question
about what time it started.

### Mixing DeepSeek and GPT across roles

Because routing is per model id, splitting roles across providers is a
`.env` change, not a code change. Since 2026-09-11 the configured split is:

| Roles | Model | Why |
| --- | --- | --- |
| `answer` (`/ask`), `extraction` (`/extract`) | `deepseek-v4-flash` | Reads filing tables reliably |
| `agent`, `decomposer`, `news_digest`, `technical`, `debate`, `risk_panel`, `research_manager`, `risk_judge` | `gpt-5.6-luna` | About half the cost, and faster |

**Why the two server-side roles went back to DeepSeek.** An all-Luna ACN run
(as-of 2026-08-28) cost $0.120 in 418 s. That's half of DeepSeek's ~$0.24 /
558 s, but its fundamentals memo came back INSUFFICIENT_EVIDENCE with 6 of 12
checklist items missing. The data was in the index. `/extract` retrieval is
deterministic (fixed `METRIC_QUERIES` through `retrieve_hybrid`, no rewriter),
and a replay showed it hands the FY2025 extraction chunk 111, which holds both
the operating-cash-flow and capex rows. Luna answered "not disclosed in the
excerpts" on 2 of 4 attempts over identical input; DeepSeek read it 4 of 4.
The misses look random: the same model reads the table on one call and not
the next. The roles that read filing excerpts therefore run on the model
that reads them reliably. The same ACN run on the split setup had 3 of 12
items missing, with free cash flow found, at ~$0.137 real in 353 s. It is
still INSUFFICIENT_EVIDENCE because the ICFR item (Item 9A) is missing. One
run per setup, so these are directional numbers, not a benchmark.

**Luna runs without reasoning in this pipeline, and that is forced, not
chosen.** On chat completions, GPT-5.x rejects function tools with any
`reasoning_effort` other than `"none"`. Every port calls with tools, and
leaving the parameter unset is no escape, because the default is not
`"none"`. So the shim sends `max_completion_tokens` (GPT-5.x 400s on
`max_tokens`), `reasoning_effort="none"` unless a caller asks for thinking,
and `"none"` regardless on any call with tools (#78, #79). `temperature` is
honoured only while reasoning is off. The query decomposer's hard-coded
`temperature=0` goes through `create_with_temperature_fallback` in case a
model rejects it. Getting reasoning back would mean moving the OpenAI path to
the Responses API. That hasn't been tried, and there's no evidence yet that
reasoning would fix the table misreads.

**A split setup breaks the assumption that the server's models are the
agent's.** `/ask` and `/extract` report their spend in `X-LLM-Usage`, and
`fundamentals_port.py` used to price that whole total at `AGENT_MODEL`. On
the split run that logged $0.0375 for ~$0.0666 of DeepSeek spend, and the
$0.75 cap counted the lower number. `/ask` also sums two models in one
request (DeepSeek answer + Luna decomposer), so the fix has to split usage
server-side, before the sum. The fix is PR #80
(`fix/price-delegated-usage-per-model`), open as of 2026-09-11. It makes the header
per-model and logs one `fundamentals-tools` cost event per model, each at
its own rate. Until it lands, logged totals under a split setup understate.

**Operating a split setup:**
- `.env` is read at process start, so restart the API server after moving a
  role. A server started before the change keeps serving the old model.
- Every model in use needs a `MODEL_PRICING` entry, or `LLM_PRICING_OVERRIDES`
  for a model not in the table yet. An unpriced model logs null cost and the
  budget cap can't fire for it.
- DeepSeek bills in CNY and can hit a 402 "Insufficient Balance". Check
  `GET https://api.deepseek.com/user/balance` (free) before blaming the
  model.

**Open.** The `ask_edgar` tool description tells the agent to "ask one broad
question that covers several checklist items". Luna follows that literally,
sending 6-7 compound questions per turn in parallel, so it can't adapt one
query to what the previous answer said (12 turns against DeepSeek's 39 for a
similar call count). On the split run, the Luna risk judge also returned
UNRESOLVED: the fabrication guard dropped 1 of 3 samples and the other two
split hold/sell. Neither has been compared across runs yet.
