# Entry point (uvicorn app.main:app): .env first, before any app import reads
# its settings. See app/shared/config.py.
#
# The composition root: it starts each context's resources and mounts each
# context's router (see CONTEXT-MAP.md), and owns nothing else but CORS and
# /health.
from app.shared.config import load_env

load_env()

from contextlib import asynccontextmanager  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.agent.trading.infrastructure.checkpointer import build_checkpointer  # noqa: E402
from app.agent.trading.infrastructure.graph import build_trading_graph  # noqa: E402
from app.agent.trading.interface.api import router as trading_router  # noqa: E402
from app.edgar_research.api import router as edgar_research_router  # noqa: E402
from app.edgar_research.application.embedding_service import EmbeddingService  # noqa: E402
from app.edgar_research.application.query_decomposer import QueryDecomposer  # noqa: E402
from app.edgar_research.infrastructure.build_info import build_info, describe  # noqa: E402
from app.edgar_research.infrastructure.repositories.db import init_pool, close_pool  # noqa: E402


logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("serving code at %s", describe())
    await init_pool()
    # Built once and shared, instead of per request: every /ask and /extract
    # used to construct a fresh OpenAI client and a fresh decomposer client,
    # so no HTTP connection was ever reused. Best-effort — a missing key or
    # provider config leaves them unset and the endpoints build their own,
    # failing then with the same error they always did.
    for name, factory in (("embedder", EmbeddingService), ("decomposer", QueryDecomposer)):
        try:
            setattr(app.state, name, factory())
        except Exception as exc:
            logging.warning("not sharing a %s client: %s", name, exc)
    async with build_checkpointer() as checkpointer:
        app.state.trading_graph = build_trading_graph(checkpointer)
        yield
    await close_pool()


app = FastAPI(title="RAG Skeleton", lifespan=lifespan)

# Browsers may call this API only from these origins. It was "*", which let
# ANY page open in the user's browser send requests to localhost:8000 — and
# /ask, /extract, /ingest, /news-assess and /trading/analyze all spend API
# credits. The default is the Vite dev server the removed edgar-ui ran on;
# set CORS_ALLOW_ORIGINS (comma-separated) for anything else, or to "" to
# allow no browser origin at all.
CORS_ALLOW_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(edgar_research_router)
app.include_router(trading_router)


@app.get("/health")
async def health():
    """What code this process is running.

    Exists because a 22-hour-stale uvicorn served a whole FIG pipeline run
    on 2026-09-13 with no symptom but a date bound that silently did
    nothing. `commit` is snapshotted at import, so it is the RUNNING
    process's commit, not the working tree's.
    """
    return {"status": "ok", **build_info()}
