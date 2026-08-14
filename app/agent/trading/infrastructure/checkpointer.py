import os
from contextlib import asynccontextmanager
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

DB_URI = os.getenv("TRADING_CHECKPOINT_DB_URI")  

connection_kwargs = {"autocommit": True, "prepare_threshold": 0}

# Every custom domain type that lands in TradingState needs an entry here —
# add to this list as Phase 2+ introduces FundamentalsReport, TechnicalReport, etc.
ALLOWED_MSGPACK_MODULES = [
    ("app.agent.trading.domain.decision_memo", "Verdict"),
    ("app.agent.trading.domain.decision_memo", "DecisionMemo"),
    ("app.agent.trading.domain.fundamentals_report", "FundamentalsReport"),
]


@asynccontextmanager
async def build_checkpointer():
    async with AsyncConnectionPool(
        conninfo=DB_URI, max_size=10, kwargs=connection_kwargs, open=False
    ) as pool:
        await pool.open()
        serde = JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_MSGPACK_MODULES)
        checkpointer = AsyncPostgresSaver(pool, serde=serde)
        await checkpointer.setup()  # idempotent — creates tables once
        yield checkpointer