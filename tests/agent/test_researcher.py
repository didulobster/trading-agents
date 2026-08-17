import app.agent.researcher as researcher
from app.agent.tools import record_tool_output, reset_run_provenance


def setup_function():
    reset_run_provenance()


def test_save_output_writes_provenance_sibling(tmp_path, monkeypatch):
    """The saved report gets a -provenance.txt sibling holding everything
    the tools returned this run, so a suspect figure in the report can be
    traced (or shown absent) after the process exits."""
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)
    record_tool_output("Revenue was $64,896 million. [ACN 10-K 2025 §Item 7]")

    path = researcher._save_output("# Memo", "ACN", "fundamentals")

    sibling = path.with_name(f"{path.stem}-provenance.txt")
    assert sibling.exists()
    assert "64,896" in sibling.read_text()


def test_save_output_skips_provenance_for_technical_mode(tmp_path, monkeypatch):
    """The technical interpreter doesn't use the research tools; at its
    save time the module-global corpus still holds the preceding
    fundamentals run's text, so pairing it with the technical report
    would attach the wrong evidence."""
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)
    record_tool_output("Leftover fundamentals corpus from the same process.")

    path = researcher._save_output("# Technical report", "ACN", "technical")

    assert not path.with_name(f"{path.stem}-provenance.txt").exists()


def test_save_output_skips_provenance_when_corpus_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)

    path = researcher._save_output("# Memo", "ACN", "fundamentals")

    assert not path.with_name(f"{path.stem}-provenance.txt").exists()
