import asyncio

import pandas as pd
import pytest

from app.agent.trading.domain.errors import VendorError
from app.agent.trading.infrastructure import price_data_port as pdp

SUFFICIENT_ROWS = pdp.MIN_BARS_REQUIRED + 5
INSUFFICIENT_ROWS = 40  # e.g. a ticker that partially IPO'd mid-year


def _fake_df(rows: int) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=rows, freq="D")
    return pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 100},
        index=idx,
    )


def test_falls_back_to_finnhub_when_yfinance_hard_fails(monkeypatch):
    """yfinance raising/returning None should trigger the Finnhub attempt."""
    monkeypatch.setattr(pdp, "_try_yfinance", lambda ticker: (None, "yfinance"))
    monkeypatch.setattr(
        pdp, "_try_finnhub", lambda ticker: (_fake_df(SUFFICIENT_ROWS), "finnhub")
    )

    df, source = asyncio.run(pdp.get_price_history("TICK"))

    assert source == "finnhub"
    assert len(df) == SUFFICIENT_ROWS


def test_falls_back_to_finnhub_when_yfinance_returns_insufficient_bars(monkeypatch):
    """yfinance succeeding but returning too few bars (e.g. a recent IPO) must
    still trigger the Finnhub attempt — not silently proceed with too little
    history for a 200-day SMA."""
    monkeypatch.setattr(
        pdp, "_try_yfinance", lambda ticker: (_fake_df(INSUFFICIENT_ROWS), "yfinance")
    )
    monkeypatch.setattr(
        pdp, "_try_finnhub", lambda ticker: (_fake_df(SUFFICIENT_ROWS), "finnhub")
    )

    df, source = asyncio.run(pdp.get_price_history("TICK"))

    assert source == "finnhub"
    assert len(df) == SUFFICIENT_ROWS


def test_yfinance_success_does_not_call_finnhub(monkeypatch):
    """When yfinance already returns enough bars, Finnhub should never be
    attempted — confirms the fallback is conditional, not unconditional."""
    finnhub_called = False

    def _finnhub_spy(ticker):
        nonlocal finnhub_called
        finnhub_called = True
        return _fake_df(SUFFICIENT_ROWS), "finnhub"

    monkeypatch.setattr(
        pdp, "_try_yfinance", lambda ticker: (_fake_df(SUFFICIENT_ROWS), "yfinance")
    )
    monkeypatch.setattr(pdp, "_try_finnhub", _finnhub_spy)

    df, source = asyncio.run(pdp.get_price_history("TICK"))

    assert source == "yfinance"
    assert finnhub_called is False


def test_raises_vendor_error_when_both_vendors_fail(monkeypatch):
    monkeypatch.setattr(pdp, "_try_yfinance", lambda ticker: (None, "yfinance"))
    monkeypatch.setattr(pdp, "_try_finnhub", lambda ticker: (None, "finnhub"))

    with pytest.raises(VendorError, match="No price data for TICK"):
        asyncio.run(pdp.get_price_history("TICK"))


def test_raises_vendor_error_when_both_vendors_return_insufficient_bars(monkeypatch):
    """Both vendors return *something*, just not enough — must still raise
    rather than silently proceed with too little history for a 200-day SMA."""
    monkeypatch.setattr(
        pdp, "_try_yfinance", lambda ticker: (_fake_df(INSUFFICIENT_ROWS), "yfinance")
    )
    monkeypatch.setattr(
        pdp, "_try_finnhub", lambda ticker: (_fake_df(INSUFFICIENT_ROWS), "finnhub")
    )

    with pytest.raises(VendorError, match="only 40 bars available"):
        asyncio.run(pdp.get_price_history("TICK"))
