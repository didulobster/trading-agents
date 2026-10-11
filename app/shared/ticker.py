"""The one ticker rule every entry point (HTTP, CLI) and the vault writer apply."""

import argparse
import re
from typing import Annotated

from pydantic import BeforeValidator

# First character alphanumeric: the ticker becomes a vault directory name
# (vault.save_output), and the old pattern `[A-Z0-9.\-]{1,10}` accepted
# ".." — a path-traversal segment. Class shares like BRK.B and BF-B still pass.
_TICKER_RE = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,9}")


def normalize_ticker(v: str) -> str:
    """Strip and upper-case a ticker, or raise ValueError if it cannot be one."""
    s = str(v).strip().upper()
    if not _TICKER_RE.fullmatch(s):
        raise ValueError(f"Invalid ticker: {v!r}")
    return s


# A request or model field holding a ticker, normalized on the way in.
Ticker = Annotated[str, BeforeValidator(normalize_ticker)]


def ticker_arg(value: str) -> str:
    """argparse `type=` for a ticker: normalized, or a clean usage error."""
    try:
        return normalize_ticker(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
