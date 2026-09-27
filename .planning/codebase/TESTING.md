---
last_mapped_commit: 8a7c506660f3af4394b728e0ea36e9b78d2baeb2
last_mapped_at: 2026-09-27
---
# Testing Patterns

**Analysis Date:** 2026-09-27

## Test Framework

**Runner:**
- pytest >=9.1.1 (dev dependency group in `pyproject.toml`)
- Config: `[tool.pytest.ini_options] pythonpath = ["."]` in `pyproject.toml`; shared setup in `tests/conftest.py`
- Async tests via the anyio pytest plugin (`@pytest.mark.anyio` + an `anyio_backend` fixture returning `"asyncio"`)

**Assertion Library:**
- Plain `assert`, `pytest.raises`

**Run Commands:**

```bash
uv run pytest -q -rs                       # All tests (CI command; -rs shows skip reasons)
uv run pytest tests/agent/trading -q       # One area
uv run pytest -q -k debate                 # By keyword
```

- 973 tests collected. No coverage tool configured.

## Test File Organization

**Location:**
- Separate `tests/` tree mirroring `app/`: `tests/agent/`, `tests/agent/trading/`, `tests/application/`, `tests/infrastructure/{chunking,edgar,parsing,queries}/`, cross-cutting tests at `tests/` root.

**Naming:**
- `test_<behaviour>.py`, named for the property guarded, not only the module: `test_node_failures_degrade.py`, `test_resume_budget_guard.py`, `test_per_run_state_isolation.py`, `test_stale_server_guards.py`.

**Structure:**

```
tests/
├── conftest.py            # load_env() + placeholder provider keys
├── fixtures/              # avgo_ohlcv_sample.csv, canary_article.json, control_article.json
├── agent/                 # researcher / tools tests
│   └── trading/           # trading pipeline: ports, nodes, routers, graph, logs
├── application/
└── infrastructure/
```

## Test Structure

**Suite Organization:**

```python
"""Guardrail tests. Mocked LLM throughout — no network, no cost.
<why these tests exist>
"""
from __future__ import annotations
import pytest
import app.agent.trading.infrastructure.debate_port as port

# ---------------------------------------------------------------------------

# Fakes

# ---------------------------------------------------------------------------

class _FakeMessages: ...

def _payload(**overrides) -> dict:
    base = {...}
    ...

def test_something(monkeypatch): ...
```

(`tests/agent/trading/test_debate_port.py`)

**Patterns:**
- Module docstring states what regression the file guards and whether it costs money (always: none).
- Flat `test_*` functions, no test classes. Section banners (`# ----`) separate fakes from tests.
- `_payload(**overrides)`-style builders produce valid defaults; tests override one field.
- `@pytest.mark.parametrize("value,text", [...])` for table-driven cases.
- `tmp_path` for any file output (e.g. `monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)`).

## Mocking

**Framework:** pytest `monkeypatch` with hand-written fake classes. No `unittest.mock` / `MagicMock`.

**Patterns:**

```python
class _FakeMessages:
    def __init__(self, payloads): self._payloads = list(payloads); self.calls = []
    async def create(self, **kwargs):
        self.calls.append(kwargs)          # record request for shape assertions
        return _Response(self._payloads.pop(0))

monkeypatch.setattr(port, "log_cost", lambda *a, **k: 0.02)
monkeypatch.setattr(port, "get_delegated_usage", lambda: {})
monkeypatch.setattr(port, "_save_output", lambda *a, **k: "vault/path")
monkeypatch.setattr(nodes, "run_synthesis", fake_run_synthesis)
monkeypatch.setattr(tools.httpx, "AsyncClient", lambda **kw: _Client())
```

**What to Mock:**
- Every LLM call (client `messages.create` / `chat.completions.create`, or higher: `run_agent`, `run_synthesis`, `_summarize_batch`, `create_with_temperature_fallback`)
- HTTP (`httpx.AsyncClient`), cost logging, vault writes, build info (`app.infrastructure.build_info.COMMIT`)
- Module flags: `tools.USE_STUBS`, `fundamentals_port._USE_MOCK`, `researcher.MAX_TURNS`

**What NOT to Mock:**
- pydantic domain models and validators, routers, guards, technical indicators (run on `tests/fixtures/avgo_ohlcv_sample.csv`)
- Checkpoint serde and Postgres round-trips (real DB when available)

**Rule:** no test may reach a paid provider. `tests/conftest.py` autouse fixture sets placeholder `DEEPSEEK_API_KEY` / `LLM_API_KEY` only when unset, because clients validate keys at construction.

## Fixtures and Factories

**Test Data:**

```python
FIXTURE = Path(__file__).resolve().parents[3] / "tests/fixtures/avgo_ohlcv_sample.csv"
```

- Builders are private module functions (`_payload`, fake report constructors) in each test file; there is no shared factory module. Only `tests/conftest.py` holds shared fixtures.

**Location:**
- `tests/fixtures/`

## Coverage

**Requirements:** None enforced.

**View Coverage:** Not configured.

## Test Types

**Unit Tests:**
- Majority: domain validators, ports with fake clients, nodes/routers, parsers, number matching.

**Integration Tests:**
- Postgres-backed, skipped when unreachable:

```python
requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="needs the checkpoint Postgres at TRADING_CHECKPOINT_DB_URI",
)
```

  (`tests/agent/trading/test_checkpoint_roundtrip.py`, `tests/infrastructure/test_keyword_search.py`). CI (`.github/workflows/tests.yml`) runs a `pgvector/pgvector:pg16` service so these do not silently skip.
- Graph tests use LangGraph `interrupt_after` for deterministic interruption (`test_checkpoint_roundtrip.py`, `test_debate_graph.py`).
- FastAPI tests in `tests/test_api_hardening.py` patch `main.app.state`.

**E2E Tests:**
- Not in pytest. Live runs are manual scripts in `scripts/` (e.g. `scripts/run_p9_battery.py`) and cost money — do not run without permission.

## Common Patterns

**Async Testing:**

```python
@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.mark.anyio
async def test_x(monkeypatch):
    ...
```

**Error Testing:**

```python
with pytest.raises(ValidationError) as exc:
    DebateTurnPayload(**_payload(stance="bogus"))
```

---

*Testing analysis: 2026-09-27*
