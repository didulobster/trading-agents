from datetime import datetime

import pytest

from app.shared import vault


def test_explicit_provenance_is_written_verbatim(tmp_path, monkeypatch):
    """The trading pipeline supplies its own captured terminal log, which
    must land in the sidecar exactly as given."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)
    log = "[news] running for ACN as of 2026-08-22\n[sentiment] aggregating 3 of 9\n"

    path = vault.save_output("# Sentiment", "ACN", "sentiment", provenance=log)

    assert path.with_name(f"{path.stem}-provenance.md").read_text() == log


def test_sentiment_and_decision_land_in_the_dated_folder(tmp_path, monkeypatch):
    """Same layout as fundamentals/technical, so one run's artifacts sit
    together in the vault rather than scattering across two levels."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    sentiment = vault.save_output("# S", "ACN", "sentiment")
    decision = vault.save_output("# D", "ACN", "decision")

    assert sentiment.parent == decision.parent
    assert sentiment.parent.parent.name == "ACN"
    assert sentiment.parent.name.isdigit() and len(sentiment.parent.name) == 8
    assert sentiment.name.startswith("ACN-sentiment-")
    assert decision.name.startswith("ACN-decision-")


# ---------------------------------------------------------------------------
# vault_run — one folder per pipeline run
# ---------------------------------------------------------------------------

def test_a_run_folder_gathers_every_artifact_of_one_run(tmp_path, monkeypatch):
    """The layout this exists to produce. Without it a run scatters six files
    into the ticker's dated folder alongside every previous run's six, and
    telling one run's artifacts from another's means reading timestamps."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    with vault.vault_run(datetime(2026, 8, 22, 7, 1, 53)) as folder:
        paths = {
            mode: vault.save_output(f"# {mode}", "ACN", mode)
            for mode in ("fundamentals", "technical", "sentiment", "decision", "debate")
        }

    assert folder == "2026-0822-070153"
    assert len({p.parent for p in paths.values()}) == 1
    run_dir = paths["decision"].parent
    assert run_dir == tmp_path / "ACN" / "20260822" / "2026-0822-070153"
    assert sorted(p.name for p in paths.values()) == [
        "ACN-debate.md",
        "ACN-decision.md",
        "ACN-fundamental.md",
        "ACN-sentiment.md",
        "ACN-technical.md",
    ]


def test_provenance_siblings_land_in_the_same_run_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    with vault.vault_run(datetime(2026, 8, 22, 7, 1, 53)):
        fundamentals = vault.save_output("# F", "ACN", "fundamentals", provenance="--- turn 1 ---")
        sentiment = vault.save_output(
            "# S", "ACN", "sentiment", provenance="the run log"
        )

    assert sorted(p.name for p in fundamentals.parent.iterdir()) == [
        "ACN-fundamental-provenance.md",
        "ACN-fundamental.md",
        "ACN-sentiment-provenance.md",
        "ACN-sentiment.md",
    ]
    assert sentiment.with_name("ACN-sentiment-provenance.md").read_text() == "the run log"


def test_a_run_that_saves_nothing_leaves_no_empty_folder(tmp_path, monkeypatch):
    """The directory is created by the first save, not by entering the block —
    otherwise a run that dies early litters the vault, which is worse than
    the scattering this replaces."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    with vault.vault_run():
        pass

    assert list(tmp_path.iterdir()) == []


def test_two_runs_get_two_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    with vault.vault_run(datetime(2026, 8, 22, 7, 1, 53)):
        first = vault.save_output("# D", "ACN", "decision")
    with vault.vault_run(datetime(2026, 8, 22, 9, 30, 0)):
        second = vault.save_output("# D", "ACN", "decision")

    assert first.parent != second.parent
    assert first.parent.parent == second.parent.parent   # same dated folder
    assert first.name == second.name == "ACN-decision.md"


def test_a_second_artifact_of_the_same_mode_refuses_to_overwrite(tmp_path, monkeypatch):
    """Unreachable today — every mode saves exactly once per run — but a
    silent overwrite would destroy a report that cost real money, and the
    filename no longer carries a timestamp to keep them apart."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    with vault.vault_run():
        first = vault.save_output("# first", "ACN", "decision")
        with pytest.raises(FileExistsError, match="would overwrite"):
            vault.save_output("# second", "ACN", "decision")

    assert first.read_text() == "# first"


def test_outside_a_run_the_flat_timestamped_layout_is_unchanged(tmp_path, monkeypatch):
    """The standalone research CLI writes one report per invocation, so it
    has nothing to gather and keeps the layout its existing notes use."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    path = vault.save_output("# Memo", "ACN", "fundamentals")

    assert path.parent == tmp_path / "ACN" / datetime.now().strftime("%Y%m%d")
    assert path.name.startswith("ACN-fundamental-")
    assert path.name.endswith(".md")


def test_the_date_folder_comes_from_the_run_start_not_the_save_time(tmp_path, monkeypatch):
    """A run that starts at 23:58 and finishes after midnight must not file
    its fundamentals under one date and its debate transcript under the
    next — that is the same scattering, harder to spot."""
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)

    with vault.vault_run(datetime(2026, 8, 22, 23, 58, 0)):
        path = vault.save_output("# D", "ACN", "decision")

    assert path.parent == tmp_path / "ACN" / "20260822" / "2026-0822-235800"


def test_the_run_folder_is_restored_on_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "MEMO_DIR", tmp_path)
    assert vault._RUN_STAMP.get() is None

    with vault.vault_run():
        assert vault._RUN_STAMP.get() is not None

    assert vault._RUN_STAMP.get() is None
