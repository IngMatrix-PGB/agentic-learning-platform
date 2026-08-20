"""AWS Bedrock answer generation via ``ChatBedrockConverse`` (langchain-aws).
Used when ``settings.runtime_mode == "aws"``.
"""

from langchain_aws import ChatBedrockConverse

from agentic_learning_platform.application.ports.answer_generator_port import IAnswerGeneratorPort
from agentic_learning_platform.config import Settings
from agentic_learning_platform.domain.models import SearchResult

_SYSTEM_PROMPT = (
    "Eres un asistente que responde EXCLUSIVAMENTE con base en el contexto proporcionado. "
    "No uses conocimiento externo ni supuestos. Si el contexto no contiene la respuesta, dilo "
    "explícitamente. Responde en el mismo idioma de la pregunta."
)


class BedrockAnswerGeneratorAdapter(IAnswerGeneratorPort):
    def __init__(self, settings: Settings) -> None:
        self._model_id = settings.bedrock_chat_model_id
        self._client = ChatBedrockConverse(model=self._model_id, region_name=settings.aws_region)

    async def generate(self, question: str, evidence: list[SearchResult]) -> str:
        context = "\n\n".join(
            f"[Fuente: {result.source_name}, página {result.page_number}]\n{result.content}"
            for result in evidence
        )
        response = await self._client.ainvoke(
            [
                ("system", _SYSTEM_PROMPT),
                ("human", f"Contexto:\n{context}\n\nPregunta: {question}"),
            ]
        )
        content = response.content
        if isinstance(content, str):
            return content
        return "".join(part if isinstance(part, str) else str(part) for part in content)
