"""Orchestrates one evaluation run: (re)creates a dedicated eval database,
ingests the synthetic corpus, runs every golden case through the
unmodified production services, and collects raw samples for `report.py`
to aggregate.

Reuses `infrastructure.di.build_adapters` and the exact same
`RetrievalService`/`IngestionService`/`QueryService` construction `app.py`
uses — no retrieval/ranking/threshold logic is reimplemented or modified
here (see docs/architecture.md's PR-005 section: this PR measures the
existing system, it does not change it).
"""

import time
from dataclasses import dataclass

from agentic_learning_platform.application.services.ingestion_service import IngestionService
from agentic_learning_platform.application.services.query_service import QueryService
from agentic_learning_platform.application.services.retrieval_service import RetrievalService
from agentic_learning_platform.config import Settings, get_settings
from agentic_learning_platform.domain.models import Citation, RequestContext
from agentic_learning_platform.evals.corpus import EVAL_HARNESS_USER_ID, ingest_eval_corpus
from agentic_learning_platform.evals.dataset import GoldenCase, load_golden_dataset
from agentic_learning_platform.evals.metrics import find_rank
from agentic_learning_platform.infrastructure.db.database_admin import recreate_database
from agentic_learning_platform.infrastructure.db.migrations.runner import run_migrations
from agentic_learning_platform.infrastructure.db.pool import close_pool, create_pool
from agentic_learning_platform.infrastructure.di import Adapters, build_adapters


@dataclass(frozen=True, slots=True)
class EvalSample:
    case: GoldenCase
    rank: int | None
    retrieval_latency_ms: float
    has_sufficient_evidence: bool
    citations: list[Citation]
    answer_text: str
    evidence_contents: list[str]


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
        retrieval_service = RetrievalService(
            adapters.embedding,
            adapters.vector_store,
            top_k=eval_settings.retrieval_top_k,
            score_threshold=eval_settings.retrieval_score_threshold,
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
        samples = [await _run_case(case, retrieval_service, query_service) for case in dataset]

        return EvalRun(settings=eval_settings, adapters=adapters, dataset=dataset, samples=samples)
    finally:
        await close_pool(pool)


async def _run_case(
    case: GoldenCase, retrieval_service: RetrievalService, query_service: QueryService
) -> EvalSample:
    context = RequestContext(
        organization_id=case.organization_id,
        course_id=case.course_id,
        user_id=EVAL_HARNESS_USER_ID,
    )

    # Timed in isolation, around the exact method PR-006 will still expose
    # (see docs/architecture.md) — the fair, reusable latency seam.
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

    return EvalSample(
        case=case,
        rank=rank,
        retrieval_latency_ms=retrieval_latency_ms,
        has_sufficient_evidence=answer.has_sufficient_evidence,
        citations=answer.citations,
        answer_text=answer.answer,
        evidence_contents=[result.content for result in outcome.results],
    )
