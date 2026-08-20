"""Orchestrates one evaluation run: (re)creates a dedicated eval database,
ingests the synthetic corpus, runs every golden case through the
unmodified production services, and collects raw samples for `report.py`
to aggregate.

Reuses `infrastructure.di.build_adapters`/`build_lexical_search_port` and the
exact same `RetrievalService`/`IngestionService`/`QueryService` construction
`app.py` uses — no retrieval/ranking/threshold/fusion logic is reimplemented
or modified here (see docs/architecture.md's PR-005/PR-006 sections: this PR
measures the existing system, it does not change it).

When `settings.retrieval_strategy == "hybrid"`, this module additionally
times the vector/lexical/fusion sub-steps directly (diagnostic only,
duplicating — never reusing — `RetrievalService`'s internal sequence) so the
comparison report can break latency down by stage. This instrumentation
lives here, in the eval harness, and nowhere in production code (see
`report.py` and docs/architecture.md's PR-006 section for why).
"""

import time
from dataclasses import dataclass

from agentic_learning_platform.application.ports.lexical_search_port import ILexicalSearchPort
from agentic_learning_platform.application.services.ingestion_service import IngestionService
from agentic_learning_platform.application.services.query_service import QueryService
from agentic_learning_platform.application.services.rank_fusion import reciprocal_rank_fusion
from agentic_learning_platform.application.services.retrieval_service import RetrievalService
from agentic_learning_platform.config import Settings, get_settings
from agentic_learning_platform.domain.models import Citation, RequestContext
from agentic_learning_platform.evals.corpus import EVAL_HARNESS_USER_ID, ingest_eval_corpus
from agentic_learning_platform.evals.dataset import GoldenCase, load_golden_dataset
from agentic_learning_platform.evals.metrics import find_rank
from agentic_learning_platform.infrastructure.db.database_admin import recreate_database
from agentic_learning_platform.infrastructure.db.migrations.runner import run_migrations
from agentic_learning_platform.infrastructure.db.pool import close_pool, create_pool
from agentic_learning_platform.infrastructure.di import (
    Adapters,
    build_adapters,
    build_lexical_search_port,
)


@dataclass(frozen=True, slots=True)
class EvalSample:
    case: GoldenCase
    rank: int | None
    retrieval_latency_ms: float
    has_sufficient_evidence: bool
    citations: list[Citation]
    answer_text: str
    evidence_contents: list[str]
    # Diagnostic-only sub-step latencies — populated only when the run's
    # retrieval_strategy is "hybrid" (see module docstring); `None`
    # otherwise, never a misleading 0.0.
    vector_latency_ms: float | None = None
    lexical_latency_ms: float | None = None
    fusion_latency_ms: float | None = None


@dataclass(frozen=True, slots=True)
class EvalRun:
    settings: Settings
    adapters: Adapters
    dataset: list[GoldenCase]
    samples: list[EvalSample]


class EvalConfigurationError(RuntimeError):
    """The current Settings configuration cannot produce a valid eval run."""


# The report always computes Recall@5 (see report.py) — retrieval_top_k
# below this silently caps it at whatever top_k actually is (e.g. equal to
# Recall@3 if top_k=3), with no error, which would misrepresent it as a
# genuine top-5 measurement (flagged in code review).
_MIN_TOP_K_FOR_RECALL_AT_5 = 5


def validate_top_k(top_k: int) -> None:
    if top_k < _MIN_TOP_K_FOR_RECALL_AT_5:
        raise EvalConfigurationError(
            f"retrieval_top_k={top_k} is below {_MIN_TOP_K_FOR_RECALL_AT_5}: this report "
            "always computes Recall@5, which would silently be capped at whatever "
            f"top_k actually returns (equal to Recall@{top_k} here), not a true top-5 "
            "measurement. Set RETRIEVAL_TOP_K>=5 before running `make eval`."
        )


def _eval_database_name(settings: Settings) -> str:
    return f"{settings.db_name}_eval"


async def run() -> EvalRun:
    base_settings = get_settings()
    validate_top_k(base_settings.retrieval_top_k)
    eval_db_name = _eval_database_name(base_settings)

    # Determinism over convenience: a stale eval DB from a previous run (or
    # from a different golden-dataset version) must never silently affect
    # results. The dedicated eval DB never shares data with the demo
    # database (whose name `base_settings.db_name` points at) or with
    # pytest's own session-scoped ephemeral database (tests/conftest.py) —
    # three separate databases, never overlapping.
    await recreate_database(base_settings.database_dsn, eval_db_name)

    eval_settings = base_settings.model_copy(update={"db_name": eval_db_name})
    await run_migrations(eval_settings)

    pool = await create_pool(eval_settings)
    try:
        adapters = build_adapters(eval_settings, pool)
        lexical_search_port = build_lexical_search_port(eval_settings, pool)
        retrieval_service = RetrievalService(
            adapters.embedding,
            adapters.vector_store,
            top_k=eval_settings.retrieval_top_k,
            score_threshold=eval_settings.retrieval_score_threshold,
            lexical_search_port=lexical_search_port,
            candidate_top_k=eval_settings.hybrid_candidate_top_k,
            rrf_k=eval_settings.hybrid_rrf_k,
        )
        ingestion_service = IngestionService(
            adapters.parser,
            adapters.embedding,
            adapters.vector_store,
            max_upload_size_mb=eval_settings.max_upload_size_mb,
            chunk_max_chars=eval_settings.chunk_max_chars,
        )
        query_service = QueryService(retrieval_service, adapters.answer_generator)

        await ingest_eval_corpus(ingestion_service)

        dataset = load_golden_dataset()
        samples = [
            await _run_case(
                case,
                retrieval_service,
                query_service,
                adapters=adapters,
                lexical_search_port=lexical_search_port,
                settings=eval_settings,
            )
            for case in dataset
        ]

        return EvalRun(settings=eval_settings, adapters=adapters, dataset=dataset, samples=samples)
    finally:
        await close_pool(pool)


async def _run_case(
    case: GoldenCase,
    retrieval_service: RetrievalService,
    query_service: QueryService,
    *,
    adapters: Adapters,
    lexical_search_port: ILexicalSearchPort | None,
    settings: Settings,
) -> EvalSample:
    context = RequestContext(
        organization_id=case.organization_id,
        course_id=case.course_id,
        user_id=EVAL_HARNESS_USER_ID,
    )

    # Timed in isolation, around the exact method PR-006 still exposes (see
    # docs/architecture.md) — the fair, reusable latency seam, unchanged in
    # shape since PR-005.
    start = time.perf_counter()
    outcome = await retrieval_service.retrieve(case.question, context)
    retrieval_latency_ms = (time.perf_counter() - start) * 1000

    rank = find_rank(outcome.results, case.expected_source, case.expected_pages)

    # A second, separate retrieval happens inside `query_service.answer()`
    # below — not reused from `outcome` above. Reusing it would require
    # changing `QueryService`'s signature to accept pre-computed retrieval
    # results, which is exactly the kind of production change this PR must
    # not make. Embeddings are deterministic, so this costs only wall-clock
    # time for the harness itself (negligible at this dataset size), never
    # correctness — and it is not what `retrieval_latency_ms` above measures.
    answer = await query_service.answer(case.question, context)

    vector_latency_ms: float | None = None
    lexical_latency_ms: float | None = None
    fusion_latency_ms: float | None = None
    if lexical_search_port is not None:
        (
            vector_latency_ms,
            lexical_latency_ms,
            fusion_latency_ms,
        ) = await _measure_hybrid_latency_breakdown(
            case.question,
            context,
            adapters=adapters,
            lexical_search_port=lexical_search_port,
            settings=settings,
        )

    return EvalSample(
        case=case,
        rank=rank,
        retrieval_latency_ms=retrieval_latency_ms,
        has_sufficient_evidence=answer.has_sufficient_evidence,
        citations=answer.citations,
        answer_text=answer.answer,
        evidence_contents=[result.content for result in outcome.results],
        vector_latency_ms=vector_latency_ms,
        lexical_latency_ms=lexical_latency_ms,
        fusion_latency_ms=fusion_latency_ms,
    )


async def _measure_hybrid_latency_breakdown(
    question: str,
    context: RequestContext,
    *,
    adapters: Adapters,
    lexical_search_port: ILexicalSearchPort,
    settings: Settings,
) -> tuple[float, float, float]:
    """Diagnostic-only: re-runs the vector/lexical/fusion sequence a THIRD
    time (see `_run_case`'s docstring for why a second one already happens),
    purely to time each stage in isolation. Never reused as the canonical
    result, never added to `RetrievalService` itself."""
    query_embedding = await adapters.embedding.embed_text(question)

    start = time.perf_counter()
    vector_results = await adapters.vector_store.search(
        query_embedding,
        organization_id=context.organization_id,
        course_id=context.course_id,
        top_k=settings.hybrid_candidate_top_k,
    )
    vector_latency_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    lexical_results = await lexical_search_port.search(
        question,
        organization_id=context.organization_id,
        course_id=context.course_id,
        top_k=settings.hybrid_candidate_top_k,
    )
    lexical_latency_ms = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    reciprocal_rank_fusion(
        vector_results, lexical_results, k=settings.hybrid_rrf_k, top_k=settings.retrieval_top_k
    )
    fusion_latency_ms = (time.perf_counter() - start) * 1000

    return vector_latency_ms, lexical_latency_ms, fusion_latency_ms
