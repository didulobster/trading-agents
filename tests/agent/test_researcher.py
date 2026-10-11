import app.agent.researcher as researcher
from app.shared import vault
from app.agent.tools import record_log_line, reset_run_provenance


def setup_function():
    reset_run_provenance()


def test_save_memo_writes_session_log_sibling(tmp_path, monkeypatch):
    """The saved report gets a -provenance.md sibling holding the run's
    full session log — terminal trace lines plus untruncated tool
    results — so a suspect figure in the report can be traced to the
    exact turn and tool output that produced it after the process exits."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)
    record_log_line("--- turn 1 ---")
    record_log_line(
        "  [tool result] Revenue was $64,896 million. [ACN 10-K 2025 §Item 7]"
    )

    path = researcher.save_memo("# Memo", "ACN", "fundamentals")

    sibling = path.with_name(f"{path.stem}-provenance.md")
    assert sibling.exists()
    content = sibling.read_text()
    assert "--- turn 1 ---" in content
    assert "64,896" in content


def test_trace_lines_are_recorded_in_session_log(tmp_path, monkeypatch, capsys):
    """_trace both prints to stderr (live console) and records to the
    session log (saved audit trail) — the same line reaches both."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    researcher._trace("[agent finished after 3 turns]")
    path = researcher.save_memo("# Memo", "ACN", "fundamentals")

    sibling = path.with_name(f"{path.stem}-provenance.md")
    assert "[agent finished after 3 turns]" in sibling.read_text()
    assert "[agent finished after 3 turns]" in capsys.readouterr().err


def test_save_memo_skips_session_log_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    path = researcher.save_memo("# Memo", "ACN", "fundamentals")

    assert not path.with_name(f"{path.stem}-provenance.md").exists()


def test_only_save_memo_attaches_the_session_log(tmp_path, monkeypatch):
    """The trading pipeline's artifacts don't call the research tools, so a
    non-empty session log at their save time belongs to some earlier run.
    They save through `vault.save_output`, which never reads it."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)
    record_log_line("Leftover fundamentals trace from the same process.")

    for mode in ("technical", "sentiment", "decision", "fundamentals"):
        path = vault.save_output("# Report", "ACN", mode)
        assert not path.with_name(f"{path.stem}-provenance.md").exists(), mode

