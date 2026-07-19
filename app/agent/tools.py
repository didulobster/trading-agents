"""
Tool schemas and dispatch for the research agent.

STEP 1 (current): check_corpus / ingest_ticker / ask_edgar / extract_metrics
return stub data so the orchestration loop can be verified in isolation.
calculate is fully real.

STEP 2: replace the stub bodies marked `# STEP 2:` with httpx calls to your
running FastAPI server. Nothing else in this file or researcher.py changes.
"""

import ast
import operator

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
            "history. Slow: 30-60s per filing. Call once with limit=3."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "limit": {"type": "integer"},
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
        "name": "calculate",
        "description": (
            "Evaluate a mathematical expression. Use for every ratio, growth "
            "rate, and percentage — never compute these yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
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
    # Truncate noisy results in the console; the model still gets the full text
    preview = result if len(result) < 300 else result[:300] + " …"
    print(f"  [tool result] {preview}")
    return result


async def _dispatch(name: str, inputs: dict) -> str:
    if name == "calculate":
        return safe_calculate(inputs["expression"])

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
                return f"Error from /ask: {resp.status_code} — {resp.text[:500]}"

            return resp.text

        if name == "ingest_ticker":
            # STEP 2: confirm this route exists, or add it to main.py
            resp = await http.post(
                f"{API_BASE}/ingest",
                json={"ticker": inputs["ticker"], "limit": inputs.get("limit", 3)},
            )
            if resp.status_code != 200:
                return f"Error from /ask: {resp.status_code} — {resp.text[:500]}"

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
            return f"{data['answer']}\n\nSources:\n{citations}"

        if name == "extract_metrics":
            resp = await http.post(f"{API_BASE}/extract", json=inputs)
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