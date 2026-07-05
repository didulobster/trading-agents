import asyncio
import json
from pathlib import Path

from app.application.embedding_service import EmbeddingService


class QuestionEmbeddingCache:
    """
    Disk-backed cache for eval question embeddings.

    Eval questions are fixed across runs — caching their embeddings avoids
    hitting the OpenAI API on every eval, and makes eval runs fast enough
    to use as a tight feedback loop during Phase 2 development.
    """

    def __init__(self, path: Path):
        self.path = path
        self._cache: dict[str, list[float]] = (
            json.loads(path.read_text()) if path.exists() else {}
        )
        self._dirty = False
        self._lock = asyncio.Lock()

    async def get_or_embed(
        self, embedder: EmbeddingService, question: str
    ) -> list[float]:
        async with self._lock:
            if question in self._cache:
                return self._cache[question]

        # Embed outside the lock so concurrent embeds don't serialize
        vec = (await embedder.embed_many([question]))[0]

        async with self._lock:
            self._cache[question] = vec
            self._dirty = True
        return vec

    def flush(self) -> None:
        if self._dirty:
            self.path.write_text(json.dumps(self._cache))
            self._dirty = False