"""The terminal-log capture behind the run's provenance file."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.agent.trading.infrastructure.run_log import capture_terminal_log

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_capture_records_stdout_and_stderr_in_write_order():
    """One shared buffer, because the pipeline writes progress to stdout and
    the research agent writes traces to stderr — a log that separated them
    would not show what happened in what order."""
    with capture_terminal_log() as log:
        print("[news] running")
        print("[trace] tool call", file=sys.stderr)
        print("[sentiment] aggregating")

    assert log() == "[news] running\n[trace] tool call\n[sentiment] aggregating\n"


def test_capture_still_writes_through_to_the_real_terminal(capsys):
    """Capturing must not silence the run — the user watches it live."""
    with capture_terminal_log() as log:
        print("visible on stdout")
        print("visible on stderr", file=sys.stderr)

    captured = capsys.readouterr()
    assert "visible on stdout" in captured.out
    assert "visible on stderr" in captured.err
    assert "visible on stdout" in log()


def test_streams_are_restored_even_when_the_run_raises():
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        with capture_terminal_log():
            raise RuntimeError("node blew up")
    except RuntimeError:
        pass

    assert sys.stdout is saved_out
    assert sys.stderr is saved_err


def test_log_is_readable_partway_through():
    with capture_terminal_log() as log:
        print("first")
        midway = log()
        print("second")
        assert midway == "first\n"
    assert "second" in log()


def test_writelines_is_captured_not_bypassed():
    """writelines delegated to the wrapped stream would print to the
    terminal without ever passing through write — visible to the user but
    absent from the provenance file."""
    with capture_terminal_log() as log:
        sys.stdout.writelines(["a\n", "b\n"])

    assert log() == "a\nb\n"


def test_stream_attribute_probes_answer_from_the_real_stream():
    """Libraries probe isatty()/encoding before formatting output. A
    TextIOBase subclass would report encoding=None and change how they
    behave; delegation keeps the real terminal's answers."""
    with capture_terminal_log():
        assert sys.stdout.encoding == sys.__stdout__.encoding
        assert sys.stdout.isatty() == sys.__stdout__.isatty()


def test_capture_survives_a_real_subprocess_run(tmp_path):
    """End-to-end guard against the capture breaking under a real
    interpreter, where stdout is a pipe rather than pytest's replacement."""
    script = tmp_path / "probe.py"
    script.write_text(
        "import sys\n"
        "from app.agent.trading.infrastructure.run_log import capture_terminal_log\n"
        "with capture_terminal_log() as log:\n"
        "    print('out line')\n"
        "    print('err line', file=sys.stderr)\n"
        "captured = log()\n"
        "assert captured == 'out line\\nerr line\\n', repr(captured)\n"
        "print('OK')\n"
    )
    # PYTHONPATH, not cwd: Python puts the *script's* directory on sys.path,
    # and the script lives in tmp_path.
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
