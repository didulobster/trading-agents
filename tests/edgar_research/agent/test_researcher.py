import app.edgar_research.agent.researcher as researcher
from app.shared import vault
from app.edgar_research.agent.tools import record_log_line, reset_run_provenance


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




def test_the_cli_saves_the_run_s_provenance_and_logs_its_tool_spend(monkeypatch):
    """Both read the per-run state, which `run_agent` creates inside the task
    `asyncio.run` starts. Read back in `main()` after the run, they saw a
    different, empty state: from 2026-09-11 (per-task state) every standalone
    memo was saved without its provenance sidecar, and the tools' server-side
    spend never reached the cost log. A 2026-10-11 ACN memo had neither."""
    from app.edgar_research.agent import tools
    from app.shared.cost import UsageSummary
    from app.shared.token_usage import TokenUsage

    async def fake_run_agent(task, system_prompt, **kw):
        tools.reset_run_provenance()                  # as the real loop does
        record_log_line("--- turn 1 ---")
        tools._state().delegated_usage["deepseek-v4-flash"] = TokenUsage(input_tokens=1000)
        return "# memo", UsageSummary()

    logged, saved = [], {}
    monkeypatch.setattr(researcher, "run_agent", fake_run_agent)
    monkeypatch.setattr(researcher, "log_cost", lambda ticker, mode, usage, model, **kw: logged.append((mode, model)) or 0.0)
    monkeypatch.setattr(researcher, "save_output", lambda *a, **kw: saved.update(kw) or "memo.md")
    monkeypatch.setattr("sys.argv", ["researcher", "ACN"])

    researcher.main()

    assert "--- turn 1 ---" in saved["provenance"]
    assert ("research", researcher.AGENT_MODEL) in logged
    assert ("research-tools", "deepseek-v4-flash") in logged
