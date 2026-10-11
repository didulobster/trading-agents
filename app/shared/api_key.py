"""The shared secret both contexts' spending endpoints require."""

import os
import secrets

from fastapi import Depends, Header, HTTPException

API_KEY_HEADER = "X-API-Key"


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Opt-in shared secret for the endpoints that spend money.

    Unset `APP_API_KEY` leaves them open — the previous behaviour, and fine
    for a server bound to 127.0.0.1 (uvicorn's default). Set it whenever the
    server is reachable by anything but you: every spending endpoint then
    needs a matching `X-API-Key` header, and the research agent's own tool
    calls send it automatically (app/edgar_research/agent/tools.py reads the same variable).
    Read per request so a test or a restart-free change can move it.
    """
    expected = os.getenv("APP_API_KEY")
    if not expected:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(401, f"missing or invalid {API_KEY_HEADER} header")


SPENDS_MONEY = [Depends(require_api_key)]
