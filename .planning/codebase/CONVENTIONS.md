---
last_mapped_commit: 8a7c506660f3af4394b728e0ea36e9b78d2baeb2
last_mapped_at: 2026-09-27
---
# Coding Conventions

**Analysis Date:** 2026-09-27

## Naming Patterns

**Files:**
- snake_case modules: `app/agent/trading/domain/decision_memo.py`, `app/application/citation_verifier.py`
- Trading LLM adapters end in `_port.py`: `app/agent/trading/infrastructure/debate_port.py`, `risk_port.py`, `synthesis_port.py`
- DB access modules end in `_repo.py`: `app/infrastructure/repositories/chunk_repo.py`
- Graph routing modules end in `_router.py`, graph nodes in `*nodes.py`: `app/agent/trading/application/debate_router.py`, `risk_nodes.py`

**Functions:**
- snake_case, verb-first: `load_env`, `require_env`, `canonical_claims`, `check_concession`, `assert_within_budget`
- Module-private helpers prefixed with `_`: `_summarize_batch`, `_save_output`, `_dispatch`

**Variables / constants:**
- Module-level settings and constants in UPPER_CASE, often read from env at import time: `MEMO_DIR`, `MAX_TURNS`, `RISK_MAX_TURNS`, `USE_STUBS` (`app/agent/tools.py`), `_USE_MOCK` (`app/agent/trading/infrastructure/fundamentals_port.py`)
- Private constants prefixed `_`: `_BLANK_SENTINELS` (`app/agent/trading/domain/debate.py`)

**Types:**
- PascalCase pydantic models: `DebateTurn`, `DebateTurnPayload`, `DecisionMemo`, `TechnicalReport`, `NewsDigest`
- `Literal` aliases for closed vocabularies: `Side = Literal["bull", "bear"]`, `Stance`, `EvidenceRef` in `app/agent/trading/domain/debate.py`
- `*Payload` = what the LLM emits (tool input schema); the non-payload model adds Python-owned fields (indices, counters, sides)
- Exceptions named for the failure: `VendorError` (`app/agent/trading/domain/errors.py`), `MissingSetting(KeyError)` (`app/config.py`)

## Code Style

**Formatting:**
- No formatter config committed. 4-space indent, double quotes, trailing commas in multi-line calls/imports.
- `from __future__ import annotations` at the top of most modules.
- Python 3.13 (`.python-version`); modern typing (`dict | None`, `list[dict]`).

**Linting:**
- ruff is used ad hoc (`.ruff_cache/` present, recent commits "Apply the four ruff cleanups"); no `[tool.ruff]` in `pyproject.toml`.
- Intentional re-exports carry `# noqa: F401` plus a comment explaining why (see `app/agent/trading/infrastructure/debate_port.py` re-exporting `create_with_temperature_fallback`, which tests patch at that name). Never let `ruff --fix` delete these.

## Import Organization

**Order:**
1. `from __future__ import annotations`
2. Standard library
3. Third-party (`pydantic`, `langgraph`, `pandas`, `pytest`)
4. First-party absolute `app.` imports

**Path Aliases:**
- None. Always absolute from repo root: `from app.agent.trading.domain.debate import DebateTurn`. pytest sets `pythonpath = ["."]` in `pyproject.toml`.
- Modules that tests monkeypatch are imported as modules: `import app.agent.trading.infrastructure.debate_port as port`.

## Layering (DDD-style)

- `domain/` — pydantic types and pure rules, no I/O (`app/domain/`, `app/agent/trading/domain/`)
- `application/` — orchestration/services/graph nodes (`app/application/`, `app/agent/trading/application/`)
- `infrastructure/` — LLM, EDGAR, DB, vendors, logging (`app/infrastructure/`, `app/agent/trading/infrastructure/`)
- `interface/` — CLI/runner (`app/agent/trading/interface/cli.py`, `runner.py`); FastAPI in `app/main.py`, Typer in `app/cli.py`

## LLM Output Rule

- The model produces content only; Python owns every index, counter, side label (see docstring of `app/agent/trading/domain/debate.py`).
- Structured output = one tool with forced `tool_choice`, validated by pydantic, via `call_with_schema_retry` in `app/agent/trading/infrastructure/structured_call.py`.
- Keep tool-schema models flat with short docstrings (they become prompt text).
- Never ask a model for an empty string; use a sentinel (`"none"`) and normalize in a `field_validator` (`_BLANK_SENTINELS`).
- Wrap Anthropic calls with `create_with_temperature_fallback` (`app/infrastructure/llm/`) because some models reject `temperature`.
- Resolve models via `model_for(...)` and call `warn_if_unpriced` (`app/infrastructure/llm/models.py`).

## Configuration

- Entry points call `load_env()` (`app/config.py`) before importing other `app` modules; library modules never call `load_dotenv`. Environment wins over `.env`.
- Required settings via `require_env(name)`, which raises `MissingSetting`.
- Template of variables: `.env.example` (never commit real values).

## Error Handling

**Patterns:**
- Validate at the boundary with pydantic; let `ValidationError` drive retries (`call_with_schema_retry`).
- Budget guards raise rather than degrade (`assert_within_budget`, `app/agent/trading/domain/budget.py`).
- Analyst node failures degrade to a flagged partial result instead of killing the run (see `tests/agent/trading/test_node_failures_degrade.py`).
- Broad `except Exception` is rare (8 occurrences under `app/`); do not add defensive try/except. Custom exceptions subclass the closest builtin so existing callers still catch them.

## Logging

**Framework:** mostly `print` for CLI progress (`app/agent/trading/interface/cli.py`, `app/agent/trading/application/nodes.py`); structured records via `app/agent/trading/infrastructure/run_log.py` and cost via `cost_log.py` / `log_cost`.

**Patterns:**
- Every paid call records cost through `log_cost`; delegated tool cost via `get_delegated_usage`.
- Run artifacts go to the vault/memo dir (`MEMO_DIR`).

## Comments

**When to Comment:**
- Explain WHY with evidence: comments cite measured incidents ("landed in `concession_trigger` on 4 of 4 live turns", "Across all 42 vault transcripts..."). Follow this: justify non-obvious choices with the observed failure.
- Long module docstrings describing design rationale are the norm in ports and domain modules.

**Docstrings:**
- Triple-quoted, prose, one-line summary then rationale. No Google/NumPy param sections.

## Function Design

**Size:** short functions; move shared helpers into `structured_call.py` or `app/infrastructure/llm/` rather than duplicating.

**Parameters:** keyword-heavy; pydantic models passed between layers.

**Return Values:** pydantic models or plain dicts (LangGraph state updates from nodes).

## Module Design

**Exports:** no `__all__`; import names directly.

**Barrel Files:** `app/infrastructure/llm/__init__.py` re-exports `LLMClient`, `get_client`, `create_with_temperature_fallback`. Other `__init__.py` files are empty.

---

*Convention analysis: 2026-09-27*
