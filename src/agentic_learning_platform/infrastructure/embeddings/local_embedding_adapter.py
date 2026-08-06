"""Local, in-process embeddings via FastEmbed (ONNX Runtime — no PyTorch,
no external service). Used when ``settings.runtime_mode == "local"``.

This mode demonstrates parsing, chunking, retrieval and citations without
AWS credentials — it is not meant to demonstrate answer-generation quality,
only that real, meaningful embeddings drive real retrieval. See
docs/architecture.md.
"""

import asyncio
from typing import cast

from fastembed import TextEmbedding

from agentic_learning_platform.application.ports.embedding_port import IEmbeddingPort
from agentic_learning_platform.config import Settings


class LocalEmbeddingAdapter(IEmbeddingPort):
    """The model is downloaded on first use (not during ``docker build``) and
    cached at ``settings.fastembed_cache_dir``, which is a persistent Docker
    volume in docker-compose.yml — later runs reuse the cache."""

    def __init__(self, settings: Settings) -> None:
        self._model_name = settings.local_embedding_model
        self._dimension = settings.embedding_dimension
        self._cache_dir = settings.fastembed_cache_dir
        self._model: TextEmbedding | None = None

    def _get_model(self) -> TextEmbedding:
        if self._model is None:
            self._model = TextEmbedding(model_name=self._model_name, cache_dir=self._cache_dir)
        return self._model

    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        vectors = self._get_model().embed(texts)
        return [cast(list[float], vector.tolist()) for vector in vectors]

    async def embed_text(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_batch_sync, texts)

    def get_dimension(self) -> int:
        return self._dimension

    def get_model_name(self) -> str:
        return self._model_name
