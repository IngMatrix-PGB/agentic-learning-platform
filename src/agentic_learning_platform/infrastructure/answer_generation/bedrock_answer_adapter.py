"""AWS Bedrock answer generation via ``ChatBedrockConverse`` (langchain-aws).
Used when ``settings.runtime_mode == "aws"``.

``stream`` is real Bedrock token streaming (``ChatBedrockConverse.astream``,
which uses Bedrock's ``InvokeModelWithResponseStream`` API), not paced
delivery of an already-complete answer. Usage/latency instrumentation is
captured here and logged — never the prompt, retrieved passages, or
generated text.
"""

import logging
import time
from collections.abc import AsyncIterator

from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError
from langchain_aws import ChatBedrockConverse

from agentic_learning_platform.application.ports.answer_generator_port import IAnswerGeneratorPort
from agentic_learning_platform.config import Settings
from agentic_learning_platform.domain.models import SearchResult
from agentic_learning_platform.exceptions import AnswerGenerationUnavailableError
from agentic_learning_platform.infrastructure.answer_generation.bedrock_pricing import (
    estimate_cost_usd,
)

_SYSTEM_PROMPT = (
    "Eres un asistente que responde EXCLUSIVAMENTE con base en el contexto proporcionado. "
    "No uses conocimiento externo ni supuestos. Si el contexto no contiene la respuesta, dilo "
    "explícitamente. Responde en el mismo idioma de la pregunta."
)

logger = logging.getLogger(__name__)


def _build_messages(question: str, evidence: list[SearchResult]) -> list[tuple[str, str]]:
    context = "\n\n".join(
        f"[Fuente: {result.source_name}, página {result.page_number}]\n{result.content}"
        for result in evidence
    )
    return [
        ("system", _SYSTEM_PROMPT),
        ("human", f"Contexto:\n{context}\n\nPregunta: {question}"),
    ]


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part if isinstance(part, str) else str(part) for part in content)
    return ""


def _usage_field_as_int(usage: dict[str, object] | None, field: str) -> int | None:
    value = usage.get(field) if usage else None
    return value if isinstance(value, int) else None


class BedrockAnswerGeneratorAdapter(IAnswerGeneratorPort):
    def __init__(self, settings: Settings) -> None:
        self._model_id = settings.bedrock_chat_model_id
        self._client = ChatBedrockConverse(
            model=self._model_id,
            region_name=settings.aws_region,
            max_tokens=settings.bedrock_max_output_tokens,
            timeout=settings.bedrock_generation_timeout_seconds,
            max_retries=settings.bedrock_max_retries,
        )

    async def stream(self, question: str, evidence: list[SearchResult]) -> AsyncIterator[str]:
        messages = _build_messages(question, evidence)
        start = time.perf_counter()
        first_token_at: float | None = None
        usage: dict[str, object] | None = None

        try:
            async for chunk in self._client.astream(messages):
                text = _content_to_text(chunk.content)
                if text:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    yield text
                if chunk.usage_metadata:
                    usage = dict(chunk.usage_metadata)
        except (ClientError, ReadTimeoutError, ConnectTimeoutError) as exc:
            # Access denied, model unavailable, throttled past the SDK's
            # bounded retries (bedrock_max_retries), or timed out — one
            # AppError for all of these (see exceptions.py's docstring),
            # not a taxonomy of every possible Bedrock-side cause. Re-raised
            # (not swallowed): if this happens after some chunks were
            # already yielded to an SSE caller, the stream error guard is
            # responsible for translating it into an `event: error` frame —
            # see routes.query_stream.
            raise AnswerGenerationUnavailableError(
                f"Bedrock generation via {self._model_id!r} failed: {exc}"
            ) from exc

        total_latency_ms = (time.perf_counter() - start) * 1000
        time_to_first_token_ms = (
            (first_token_at - start) * 1000 if first_token_at is not None else None
        )
        input_tokens = _usage_field_as_int(usage, "input_tokens")
        output_tokens = _usage_field_as_int(usage, "output_tokens")
        total_tokens = _usage_field_as_int(usage, "total_tokens")
        estimated_cost = estimate_cost_usd(
            self._model_id, input_tokens=input_tokens, output_tokens=output_tokens
        )
        logger.info(
            "bedrock_generation_completed model_id=%s input_tokens=%s output_tokens=%s "
            "total_tokens=%s time_to_first_token_ms=%s total_latency_ms=%.2f "
            "estimated_cost_usd=%s",
            self._model_id,
            input_tokens,
            output_tokens,
            total_tokens,
            f"{time_to_first_token_ms:.2f}" if time_to_first_token_ms is not None else None,
            total_latency_ms,
            estimated_cost,
        )
