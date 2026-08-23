"""Capture a run's terminal output verbatim while still showing it live.

The research agent already keeps a provenance log, but it records only its
own tool calls via `record_log_line` — it cannot see the trading pipeline's
node output, which is written straight to stdout. Reconstructing a run from
the report alone is exactly the after-the-fact inference the provenance
artifact exists to avoid, so the pipeline captures the real terminal
instead.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Callable, Iterator, TextIO


class _Tee:
    """Writes through to the real stream and records what it wrote.

    Deliberately not an io.TextIOBase subclass: that base class defines
    `encoding`, `errors` and friends as None, which would shadow the real
    stream's values for any caller that probes them. A plain object with
    __getattr__ delegation answers every such probe from the wrapped stream.
    """

    def __init__(self, stream: TextIO, sink: list[str]) -> None:
        self._stream = stream
        self._sink = sink

    def write(self, text: str) -> int:
        self._sink.append(text)
        return self._stream.write(text)

    def writelines(self, lines) -> None:
        # Defined explicitly: delegating it would write through the real
        # stream without ever passing the text through `write`, so those
        # lines would appear on the terminal but not in the log.
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


@contextmanager
def capture_terminal_log() -> Iterator[Callable[[], str]]:
    """Tee stdout and stderr into one chronological buffer.

    Both streams share a single sink on purpose. The pipeline's progress and
    reports go to stdout while the research agent's traces go to stderr; on
    the terminal they interleave, and a log that separated them would no
    longer show what happened in what order — which is the one thing the
    provenance file is for.

    Yields a callable rather than the buffer so the text can be read at any
    point, including partway through, without the caller holding a reference
    to a list that is still being appended to.
    """
    sink: list[str] = []
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = _Tee(saved_out, sink)  # type: ignore[assignment]
    sys.stderr = _Tee(saved_err, sink)  # type: ignore[assignment]
    try:
        yield lambda: "".join(sink)
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
