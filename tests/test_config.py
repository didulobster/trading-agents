"""Configuration: one way `.env` is loaded, clear errors for what is required.

docs/code_review.md, Medium #12: thirteen `load_dotenv` calls, some with
`override=True` in library modules, made shell-vs-.env precedence depend on
import order; required settings failed as a bare KeyError at import time;
EMBEDDING_MODEL and OPENAI_MODEL were configurable in name only.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import app.config as config
from app.application.embedding_service import EmbeddingService
from app.config import MissingSetting, require_env

APP = Path(__file__).resolve().parents[1] / "app"

# The dead pre-refactor PDF pipeline, slated for deletion (Low items in
# docs/code_review.md). Nothing imports either at runtime.
_DEAD_MODULES = {"ingest.py", "db_postgres.py"}


def test_load_env_never_overrides_the_environment(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "load_dotenv", lambda **kw: calls.append(kw))
    config.load_env()
    assert calls == [{"override": False}]


def test_a_missing_required_setting_says_what_to_do(monkeypatch):
    monkeypatch.delenv("LOOP_MAX_TURNS", raising=False)
    with pytest.raises(MissingSetting) as exc:
        require_env("LOOP_MAX_TURNS")
    message = str(exc.value)
    assert message.startswith("LOOP_MAX_TURNS is not set")
    assert ".env.example" in message
    assert isinstance(exc.value, KeyError)   # existing `except KeyError` still works


def test_a_set_setting_is_returned(monkeypatch):
    monkeypatch.setenv("LOOP_MAX_TURNS", "45")
    assert require_env("LOOP_MAX_TURNS") == "45"


def test_only_app_config_loads_dotenv():
    """Library modules loading .env — with override=True, in checkpointer.py
    and llm.py — is what made precedence depend on import order."""
    offenders = []
    for path in APP.rglob("*.py"):
        if path.name in _DEAD_MODULES or path == APP / "config.py":
            continue
        source = path.read_text()
        if re.search(r"\bload_dotenv\b", source) or "override=True" in source:
            offenders.append(str(path.relative_to(APP)))
    assert offenders == []


@pytest.mark.parametrize("module", [
    "main.py", "cli.py", "agent/researcher.py", "agent/trading/interface/cli.py",
])
def test_entry_points_load_env_before_any_other_app_import(module):
    """Settings are read at import time all over the app (every port's
    model_for), so the load must come before the first other app import."""
    tree = ast.parse((APP / module).read_text())
    first_app_import = None
    load_line = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
            if node.module == "app.config":
                continue
            first_app_import = min(first_app_import or node.lineno, node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "load_env"
        ):
            load_line = node.lineno
    assert load_line is not None, f"{module} never calls load_env()"
    assert load_line < first_app_import


def test_embedding_model_setting_takes_effect(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-ada-002")
    assert EmbeddingService().model == "text-embedding-ada-002"


def test_embedding_model_defaults_to_the_one_the_schema_is_sized_for(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    assert EmbeddingService().model == "text-embedding-3-small"


def test_openai_model_is_gone_from_the_example_env():
    """Read by nothing; it was only recorded into battery manifests, where it
    looked like configuration that had shaped the run."""
    example = (APP.parent / ".env.example").read_text()
    assert "OPENAI_MODEL" not in example
