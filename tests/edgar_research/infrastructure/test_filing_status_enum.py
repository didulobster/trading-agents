"""The Python `FilingStatus` and the database's `filing_status` enum must
hold the same values. `METRICS_EXTRACTED` lived in Python alone for months:
the one command that set it would have failed on write, and any query
filtering on it raised `InvalidTextRepresentation`."""

from __future__ import annotations

import os

import pytest

from app.edgar_research.domain.values import FilingStatus

DB_URI = os.getenv("POSTGRES_DATABASE_URL")


def _db_values() -> set[str] | None:
    if not DB_URI:
        return None
    import psycopg

    try:
        with psycopg.connect(DB_URI, connect_timeout=2) as conn:
            row = conn.execute("SELECT enum_range(NULL::filing_status)::text[]").fetchone()
    except psycopg.OperationalError:
        return None
    return set(row[0])


def test_python_and_database_filing_statuses_match():
    db = _db_values()
    if db is None:
        pytest.skip("needs the app database at POSTGRES_DATABASE_URL")
    assert {s.value for s in FilingStatus} == db
