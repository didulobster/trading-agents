"""The vault: where every run's artifacts land, one folder per run."""

import contextlib
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from app.shared.config import require_env
from app.shared.ticker import normalize_ticker

MEMO_DIR = Path.home() / require_env("MEMO_DIR")


# The vault filename stem for each mode, minus the ticker. "fundamentals" is
# the mode but "fundamental" is the filename, which is a wart old enough to
# be in people's muscle memory — kept rather than fixed, since renaming it
# would orphan every existing note's links.
_MODE_STEMS = {
    "news": "news",
    "technical": "technical",
    "fundamentals": "fundamental",
    "sentiment": "sentiment",
    "decision": "decision",
    "decision_failed": "decision-FAILED",
    "decision_aborted": "decision-ABORTED",
    "debate": "debate",
    "risk": "risk",
}

# Modes that file under MEMO_DIR/<ticker>/<date>/ rather than flat under the
# ticker. Everything the trading pipeline writes, which is what makes a
# per-run folder worth having at all.
_DATED_MODES = frozenset(
    {
        "technical", "fundamentals", "sentiment", "decision", "decision_failed",
        "decision_aborted", "debate", "risk",
    }
)

# The instant one pipeline run started, set by `vault_run`; None outside one.
#
# A context variable rather than a parameter threaded through six ports, because
# the two halves of a run save at different times and through different call
# stacks — technical and fundamentals from inside their nodes while the graph
# is still executing, sentiment/decision/debate from the CLI after it
# finishes. Anything computed per call (including datetime.now()) puts those
# halves in different folders, which is the problem being fixed.
#
# The whole datetime, not the formatted name: the DATE folder has to come
# from the same instant too. A run that starts at 23:58 and finishes at
# 00:02 would otherwise file its fundamentals under one date and its debate
# transcript under the next — the same scattering, harder to spot.
#
# A ContextVar and not a plain module global: the API server can run two
# pipelines at once, and each request's task must see its own folder.
_RUN_STAMP: ContextVar[datetime | None] = ContextVar("vault_run_stamp", default=None)


@contextlib.contextmanager
def vault_run(stamp: datetime | None = None):
    """Give every artifact saved inside this block ONE run folder.

    Yields the folder name. The directory is not created here — it is created
    by the first `save_output` that lands in it, so a run that dies before
    writing anything leaves no empty folder behind.

    Restores whatever was set before rather than clearing to None, so nesting
    is safe even though nothing nests today.
    """
    token = _RUN_STAMP.set(stamp or datetime.now())
    try:
        yield _RUN_STAMP.get().strftime(_RUN_FOLDER_FORMAT)
    finally:
        _RUN_STAMP.reset(token)


_RUN_FOLDER_FORMAT = "%Y-%m%d-%H%M%S"


def save_output(
    content: str,
    ticker: str,
    mode: str,
    cost_usd: float | None = None,
    provenance: str | None = None,
    model: str | None = None,
) -> Path:
    """Save output with timestamp. Returns the path.

    `provenance`, when given and non-blank, is written verbatim to a
    `-provenance.md` sidecar beside the artifact. `model` labels the cost
    footer, so pass it with `cost_usd`.

    Inside a `vault_run` block the artifacts of one run share a folder and
    drop the per-file timestamp:

        <ticker>/20260822/2026-0822-070153/ACN-fundamental.md

    Outside one — the standalone research CLI, which writes a single report —
    the old flat layout is kept, timestamp in the filename.

    The ticker becomes a directory name, so it is validated here as well as at
    the entry points — this is the last place that can stop a traversal.
    """
    ticker = normalize_ticker(ticker)
    if cost_usd is not None:
        content = content.rstrip("\n") + f"\n\n---\n**LLM cost:** ${cost_usd:.4f} ({model})\n"
    # Inside a run, every path is derived from the instant the RUN started,
    # not the instant this file happens to be written.

    run_stamp = _RUN_STAMP.get()
    now = run_stamp or datetime.now()
    stem = _MODE_STEMS.get(mode)
    parent = MEMO_DIR / ticker
    if mode in _DATED_MODES:
        parent = parent / now.strftime("%Y%m%d")

    if run_stamp is not None:
        # One folder per run, so the timestamp is on the folder and not
        # repeated on every file inside it.
        parent = parent / now.strftime(_RUN_FOLDER_FORMAT)
        filename = f"{ticker}-{stem}.md" if stem else f"{ticker}.md"
    else:
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        filename = (
            f"{ticker}-{stem}-{timestamp}.md" if stem else f"{ticker}-{timestamp}.md"
        )

    out_path = parent / filename
    if run_stamp is not None and out_path.exists():
        # Two artifacts of the same kind in one run. Unreachable today —
        # every mode is saved exactly once per run — so if it happens the
        # honest answer is to say so rather than overwrite a report that
        # cost real money to produce.
        raise FileExistsError(
            f"{out_path} already exists in this run's folder — a second "
            f"'{mode}' artifact would overwrite the first. Nothing was written."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)

    # Saved as .md (not .txt) so Obsidian's file explorer, which hides
    # unknown extensions by default, shows it beside its report.
    if provenance and provenance.strip():
        out_path.with_name(f"{out_path.stem}-provenance.md").write_text(provenance)

    return out_path
