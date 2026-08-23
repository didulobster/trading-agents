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


def test_explicit_provenance_is_written_verbatim(tmp_path, monkeypatch):
    """The trading pipeline supplies its own captured terminal log, which
    must land in the sidecar exactly as given."""
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)
    log = "[news] running for ACN as of 2026-08-22\n[sentiment] aggregating 3 of 9\n"

    path = researcher._save_output("# Sentiment", "ACN", "sentiment", provenance=log)

    assert path.with_name(f"{path.stem}-provenance.md").read_text() == log


def test_explicit_provenance_beats_the_session_log(tmp_path, monkeypatch):
    """Both are available here; the explicit one wins. Otherwise a pipeline
    artifact would be paired with whatever trace the preceding fundamentals
    run happened to leave in the module global."""
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)
    record_log_line("Leftover fundamentals trace from the same process.")

    path = researcher._save_output(
        "# Memo", "ACN", "fundamentals", provenance="the real run log"
    )

    content = path.with_name(f"{path.stem}-provenance.md").read_text()
    assert content == "the real run log"
    assert "Leftover" not in content


def test_pipeline_modes_never_inherit_the_session_log(tmp_path, monkeypatch):
    """Same reasoning as technical mode, extended to the artifacts the
    trading CLI writes: they don't call the research tools, so a non-empty
    session log at their save time belongs to some earlier run."""
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)
    record_log_line("Leftover fundamentals trace from the same process.")

    for mode in ("technical", "sentiment", "decision"):
        path = researcher._save_output("# Report", "ACN", mode)
        assert not path.with_name(f"{path.stem}-provenance.md").exists(), mode


def test_sentiment_and_decision_land_in_the_dated_folder(tmp_path, monkeypatch):
    """Same layout as fundamentals/technical, so one run's artifacts sit
    together in the vault rather than scattering across two levels."""
    monkeypatch.setattr(researcher, "MEMO_DIR", tmp_path)

    sentiment = researcher._save_output("# S", "ACN", "sentiment")
    decision = researcher._save_output("# D", "ACN", "decision")

    assert sentiment.parent == decision.parent
    assert sentiment.parent.parent.name == "ACN"
    assert sentiment.parent.name.isdigit() and len(sentiment.parent.name) == 8
    assert sentiment.name.startswith("ACN-sentiment-")
    assert decision.name.startswith("ACN-decision-")
