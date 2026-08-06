"""Port for turning text into embedding vectors.

One implementation per ``Settings.runtime_mode`` — never both active in the
same process. Selected once at startup by ``infrastructure.di``.
"""

from abc import ABC, abstractmethod


class IEmbeddingPort(ABC):
    @abstractmethod
    async def embed_text(self, text: str) -> list[float]: ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    def get_dimension(self) -> int: ...

    @abstractmethod
    def get_model_name(self) -> str: ...
