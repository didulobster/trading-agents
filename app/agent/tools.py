"""
Tool schemas and dispatch for the research agent.
"""

import ast
import operator
import re
import sys

import httpx


# Base URL of your running FastAPI server. Override when you wire step 2.
API_BASE = "http://localhost:8000"
HTTP_TIMEOUT = 300.0  # ingestion can be slow; give it room


# ---------------------------------------------------------------------------
# Tool schemas — sent to the model so it knows what it can call.
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "check_corpus",
        "description": (
            "Check what filings are available for a ticker before asking "
            "questions. Always call this first for any ticker. Returns filing "
            "count, date range, and chunk counts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "ingest_ticker",
        "description": (
            "Ingest SEC filings for a ticker not in the corpus or lacking "
            "history. Slow: 30-60s per filing. Call once with limit=3. "
            "Defaults to 10-K; set form_type to '10-Q' or '8-K' for others."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "limit": {"type": "integer"},
                "form_type": {
                    "type": "string",
                    "description": "Filing type to ingest: '10-K', '10-Q', or '8-K'. Default: '10-K'",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "ask_edgar",
        "description": (
            "Ask one specific question about SEC filings. Returns an answer "
            "with citations and source excerpts. Best for cross-section "
            "analysis, year-over-year comparisons, risk factors, MD&A "
            "commentary, and segment breakdowns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "tickers": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["question"],
        },
    },
    {
        "name": "extract_metrics",
        "description": (
            "Extract structured financial metrics (revenue, gross margin, "
            "FCF, SBC%, net dollar retention) for a ticker and filing period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "fiscal_period": {"type": "string", "description": "e.g. 'FY2025' or 'Q1 2026'"},
                "filing_type": {"type": "string", "description": "e.g. '10-K' or '10-Q'"},
                "filed_date": {"type": "string", "format": "date"},
                "filed_after": {"type": "string", "format": "date"},
                "filed_before": {"type": "string", "format": "date"},
            },
            "required": ["ticker", "fiscal_period", "filing_type", "filed_date"],
        },
    },
    {
        "name": "check_latest_filings",
        "description": (
            "Check SEC EDGAR for the latest filings (10-K, 10-Q, 8-K) for a "
            "ticker and compare with what is already in the corpus. Returns "
            "which filings are new and not yet ingested. Use this to ensure "
            "the corpus has the most recent reports before running analysis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "calculate",
        "description": (
            "Evaluate a mathematical expression. Use for EVERY ratio, growth "
            "rate, margin and percentage — never compute one yourself. Each "
            "numeric literal in the expression must be a figure you retrieved "
            "verbatim from a filing in this session, and must be declared in "
            "`inputs` with its fiscal period and source citation. Do not "
            "reconstruct figures with arithmetic (no 27.6*1000): retrieve the "
            "exact value instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "e.g. '(32667.3 - 28262.9) / 28262.9 * 100'. Every "
                        "figure must appear exactly as the filing states it."
                    ),
                },
                "inputs": {
                    "type": "array",
                    "description": (
                        "One entry per retrieved figure used in the expression. "
                        "Scalars that are part of the operation itself (100 for "
                        "percent, 2 for a square root) do not need declaring."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "number"},
                            "label": {"type": "string", "description": "e.g. 'total net sales'"},
                            "fiscal_period": {"type": "string", "description": "e.g. 'FY2024'"},
                            "source": {"type": "string", "description": "e.g. 'ASML 20-F 2026 §Item 6'"},
                        },
                        "required": ["value", "label", "fiscal_period", "source"],
                    },
                },
            },
            "required": ["expression", "inputs"],
        },
    }
]


# ---------------------------------------------------------------------------
# Safe calculator — AST-walking evaluator, not eval(). Permits only numeric
# literals and + - * / ** and unary minus. Anything else (calls, names,
# attribute access) raises.
# ---------------------------------------------------------------------------

_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def safe_calculate(expression: str) -> str:
    try:
        node = ast.parse(expression, mode="eval").body
        return str(_eval_node(node))
    except Exception as e:
        return f"Error evaluating '{expression}': {e}"


def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("only numeric constants allowed")
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](
            _eval_node(node.left), _eval_node(node.right)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"disallowed expression element: {type(node).__name__}")


# ---------------------------------------------------------------------------
# Dispatch. Each branch prints its call/result so you can watch the agent
# reason. Replace the stub branches in step 2.
# ---------------------------------------------------------------------------

# Toggle to False in step 2 once the HTTP branches are wired and tested.
USE_STUBS = False


async def execute_tool(name: str, inputs: dict) -> str:
    print(f"  [tool call] {name}({inputs})")
    result = await _dispatch(name, inputs)

    # Feed tool output into the provenance corpus so calculate() can verify
    # its inputs were actually retrieved. Exclusions:
    #   - calculate itself: computed results must not count as retrieved,
    #     or derived figures launder themselves one call at a time
    #   - the verifier's warning block: a flagged figure appears inside the
    #     answer text, and recording it would make the fabrication count
    #     as "returned by a tool" for later calculate calls
    if name != "calculate":
        clean = result.split("WARNING — these figures")[0]
        record_tool_output(clean)

    # Truncate noisy results in the console; the model still gets the full text
    preview = result if len(result) < 300 else result[:300] + " …"
    print(f"  [tool result] {preview}", file=sys.stderr)
    return result


async def _dispatch(name: str, inputs: dict) -> str:
    if name == "calculate":
        err = validate_calculate_inputs(
            inputs["expression"], inputs.get("inputs", [])
        )
        if err:
            return err
        result = safe_calculate(inputs["expression"])
        record_calc_result(result)
        return result

    if USE_STUBS:
        return _stub(name, inputs)

    # STEP 2: real HTTP calls. Un-stub by setting USE_STUBS = False and
    # confirming each endpoint below matches your FastAPI routes.
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as http:
        if name == "check_corpus":
            # STEP 2: confirm this route/param exists, or add it to main.py
            resp = await http.get(
                f"{API_BASE}/corpus-status", params={"ticker": inputs["ticker"]}
            )
            if resp.status_code != 200:
                return f"Error from /check_corpus: {resp.status_code} — {resp.text[:500]}"

            return resp.text

        if name == "ingest_ticker":
            payload = {"ticker": inputs["ticker"], "limit": inputs.get("limit", 3)}
            if "form_type" in inputs:
                payload["form_type"] = inputs["form_type"]
            resp = await http.post(f"{API_BASE}/ingest", json=payload)
            if resp.status_code != 200:
                return f"Error from /ingest_ticker: {resp.status_code} — {resp.text[:500]}"

            return resp.text

        if name == "ask_edgar":
            resp = await http.post(
                f"{API_BASE}/ask",
                json={
                    "question": inputs["question"],
                    "tickers": inputs.get("tickers"),
                },
            )
            if resp.status_code != 200:
                return f"Error from /ask: {resp.status_code} — {resp.text[:500]}"
            
            data = resp.json()
            citations = "\n".join(
                f"  [{c['citation']}] sim={c['similarity']:.3f}"
                for c in data.get("chunks", [])
            )
            out = f"{data['answer']}\n\nSources:\n{citations}"
            if data.get("unverified"):
                out += (
                    f"\n\nWARNING — these figures in the above answer do not "
                    f"appear in any retrieved filing chunk: "
                    f"{data['unverified']}. Do not use them in the memo or in "
                    f"calculate inputs without re-retrieving them first."
                )
            return out

        if name == "extract_metrics":
            resp = await http.post(f"{API_BASE}/extract", json=inputs)
            if resp.status_code != 200:
                return f"Error from /extract_metrics: {resp.status_code} — {resp.text[:500]}"
            return resp.text

        if name == "check_latest_filings":
            resp = await http.post(
                f"{API_BASE}/latest-filings",
                json={"ticker": inputs["ticker"]},
            )
            if resp.status_code != 200:
                return f"Error from /latest-filings: {resp.status_code} — {resp.text[:500]}"
            return resp.text

    return f"Unknown tool: {name}"


def _stub(name: str, inputs: dict) -> str:
    if name == "check_corpus":
        return (
            "STUB: AVGO has 3 filings, 2023-12-14 to 2025-12-18, 487 chunks."
        )
    if name == "ask_edgar":
        return (
            "STUB ANSWER: Broadcom's semiconductor solutions revenue was "
            "$36,858 million in FY2025 vs $30,096 million in FY2024, +22%. "
            "[AVGO 10-K 2025 §Item 7]"
        )
    if name == "ingest_ticker":
        return f"STUB: ingested {inputs.get('ticker')}, {inputs.get('limit', 3)} filings."
    if name == "extract_metrics":
        return "STUB: revenue=63887, gross_margin_pct=68.0, confidence=stated"
    return f"Unknown tool: {name}"

# ---------------------------------------------------------------------------
# 2. Validator — rejects literals the model didn't account for
# ---------------------------------------------------------------------------

# Scalars that belong to the operation rather than to a filing.
_OPERATION_SCALARS = {1.0, 2.0, 3.0, 4.0, 12.0, 100.0, 365.0}

# Unit-conversion multipliers — the fingerprint of a remembered figure.
_UNIT_MULTIPLIERS = {1000.0, 1000000.0, 1_000_000_000.0}


def validate_calculate_inputs(expression: str, inputs: list[dict]) -> str | None:
    """
    Three checks, in order of how cheaply they fail:
      1. no unit-conversion multipliers (fingerprint of a remembered figure)
      2. every literal in the expression is declared in `inputs`
      3. every declared input actually appeared in some tool output this run
    """
    literals = {
        float(m) for m in re.findall(r"\d+\.?\d*(?:[eE][+-]?\d+)?", expression)
    }
    declared = {
        float(i["value"]) for i in inputs if i.get("value") is not None
    }
 
    # 1 — reconstruction fingerprint
    reconstructed = literals & _UNIT_MULTIPLIERS
    if reconstructed:
        return (
            f"Rejected: expression contains unit-conversion multiplier(s) "
            f"{sorted(reconstructed)}. A figure retrieved from a filing is a "
            f"single literal in the filing's own units. Retrieve the exact "
            f"value and call calculate again."
        )
 
    # 2 — undeclared literals
    unaccounted = literals - declared - _OPERATION_SCALARS
    if unaccounted:
        return (
            f"Rejected: these numbers appear in the expression but are not "
            f"declared in `inputs`: {sorted(unaccounted)}. Every figure must "
            f"be retrieved from a filing and declared with its fiscal period "
            f"and source."
        )
 
    # 3 — declared but never returned by any tool
    corpus = _provenance_corpus()
    if corpus:
        unsourced = [
            i for i in inputs
            if i.get("value") is not None
            and float(i["value"]) not in _OPERATION_SCALARS
            and not _appears_in_output(float(i["value"]), corpus)
        ]
        if unsourced:
            detail = "; ".join(
                f"{i['value']} ({i.get('label', 'unlabelled')})"
                for i in unsourced
            )
            return (
                f"Rejected: no tool returned these figures during this run: "
                f"{detail}. You cited a source for them, but the value never "
                f"appeared in any ask_edgar or extract_metrics result. Either "
                f"retrieve the figure first, or — if you derived it yourself — "
                f"show the derivation as a separate calculate call using only "
                f"retrieved figures."
            )
 
    return None

# ---------------------------------------------------------------------------
# Run-scoped store of everything the tools have returned.
#
# Module-level, which assumes one agent run per process — true for the CLI.
# If you ever run concurrent agents in one process, make this a context
# object passed through execute_tool instead.
# ---------------------------------------------------------------------------
 
_RETRIEVED_TEXT: list[str] = []
_CALC_RESULTS: list[float] = []
 
def reset_run_provenance() -> None:
    """Call once at the start of each agent run."""
    _RETRIEVED_TEXT.clear()
    _CALC_RESULTS.clear()
 
def record_calc_result(value: str | float) -> None:
    try:
        _CALC_RESULTS.append(float(value))
    except (TypeError, ValueError):
        pass

def get_calc_results() -> list[float]:
    return list(_CALC_RESULTS)

def get_provenance_corpus() -> str:
    return "\n".join(_RETRIEVED_TEXT)

def record_tool_output(text: str) -> None:
    """Record a tool result so its figures count as retrieved."""
    if text:
        _RETRIEVED_TEXT.append(text)
 
 
def _provenance_corpus() -> str:
    return "\n".join(_RETRIEVED_TEXT)

# ---------------------------------------------------------------------------
# Number matching — a tool returns "€11,384.0 million"; calculate gets 11384.0
# ---------------------------------------------------------------------------
 
def _variants(value: float) -> set[str]:
    """String forms a tool output might use for this value."""
    out: set[str] = set()
    if value == int(value):
        n = int(value)
        out.update({str(n), f"{n:,}"})
        # a tool may render a whole number with one decimal
        out.update({f"{n}.0", f"{n:,}.0"})
    else:
        out.update({
            f"{value}", f"{value:,}",
            f"{value:.1f}", f"{value:,.1f}",
            f"{value:.2f}", f"{value:,.2f}",
        })
    return out
 
 
def _appears_in_output(value: float, corpus: str) -> bool:
    return any(v in corpus for v in _variants(value))
 