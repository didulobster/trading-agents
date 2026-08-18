import app.agent.researcher as researcher
from app.agent.tools import record_log_line, reset_run_provenance


def setup_function():
    reset_run_provenance()


def test_save_output_writes_session_log_sibling(tmp_path, monkeypatch):
    """The saved report gets a -provenance.md sibling holding the run's
    full session log — terminal trace lines plus untruncated tool
    results — so a suspect figure in the report can be traced to the
    exact turn and tool output that produced it after the process exits."""
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)
    record_log_line("--- turn 1 ---")
    record_log_line(
        "  [tool result] Revenue was $64,896 million. [ACN 10-K 2025 §Item 7]"
    )

    path = researcher._save_output("# Memo", "ACN", "fundamentals")

    sibling = path.with_name(f"{path.stem}-provenance.md")
    assert sibling.exists()
    content = sibling.read_text()
    assert "--- turn 1 ---" in content
    assert "64,896" in content


def test_trace_lines_are_recorded_in_session_log(tmp_path, monkeypatch, capsys):
    """_trace both prints to stderr (live console) and records to the
    session log (saved audit trail) — the same line reaches both."""
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)

    researcher._trace("[agent finished after 3 turns]")
    path = researcher._save_output("# Memo", "ACN", "fundamentals")

    sibling = path.with_name(f"{path.stem}-provenance.md")
    assert "[agent finished after 3 turns]" in sibling.read_text()
    assert "[agent finished after 3 turns]" in capsys.readouterr().err


def test_save_output_skips_session_log_for_technical_mode(tmp_path, monkeypatch):
    """The technical interpreter doesn't use the research tools; at its
    save time the module-global session log still holds the preceding
    fundamentals run's trace, so pairing it with the technical report
    would attach the wrong evidence."""
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)
    record_log_line("Leftover fundamentals trace from the same process.")

    path = researcher._save_output("# Technical report", "ACN", "technical")

    assert not path.with_name(f"{path.stem}-provenance.md").exists()


def test_save_output_skips_session_log_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)

    path = researcher._save_output("# Memo", "ACN", "fundamentals")

    assert not path.with_name(f"{path.stem}-provenance.md").exists()
