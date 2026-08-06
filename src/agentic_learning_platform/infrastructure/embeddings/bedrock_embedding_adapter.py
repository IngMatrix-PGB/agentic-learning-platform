"""AWS Bedrock embeddings via ``langchain-aws``. Used when
``settings.runtime_mode == "aws"``.
"""

from langchain_aws import BedrockEmbeddings

from agentic_learning_platform.application.ports.embedding_port import IEmbeddingPort
from agentic_learning_platform.config import Settings


class BedrockEmbeddingAdapter(IEmbeddingPort):
    def __init__(self, settings: Settings) -> None:
        self._model_id = settings.bedrock_embedding_model_id
        self._dimension = settings.embedding_dimension
        self._client = BedrockEmbeddings(
            model_id=self._model_id,
            region_name=settings.aws_region,
            dimensions=self._dimension,
        )

    async def embed_text(self, text: str) -> list[float]:
        return await self._client.aembed_query(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await self._client.aembed_documents(texts)

    def get_dimension(self) -> int:
        return self._dimension

    def get_model_name(self) -> str:
        return self._model_id
