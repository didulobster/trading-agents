"""EMBEDDING_MODEL is configurable, and defaults to the model the schema's
vector column is sized for (see tests/shared/test_config.py for the rest of
the configuration rules)."""

from app.edgar_research.application.embedding_service import EmbeddingService


def test_embedding_model_setting_takes_effect(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-ada-002")
    assert EmbeddingService().model == "text-embedding-ada-002"


def test_embedding_model_defaults_to_the_one_the_schema_is_sized_for(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    assert EmbeddingService().model == "text-embedding-3-small"
