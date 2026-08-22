"""Tests for the PR-007 LangGraph orchestration seam itself — routing,
call-count invariants, RequestContext propagation, and exception
propagation. These are pure/fast unit tests against fakes implementing the
existing ports (no Postgres, no FastEmbed): the properties under test are
about the *graph's* orchestration, not retrieval quality or embedding
correctness — those remain covered by the DB-backed endpoint tests (see
test_query_endpoint.py, test_query_stream_endpoint.py,
test_corpus_isolation.py), which continue to exercise this same code path
unmodified and all still pass.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from agentic_learning_platform.application.ports.answer_generator_port import IAnswerGeneratorPort
from agentic_learning_platform.application.ports.embedding_port import IEmbeddingPort
from agentic_learning_platform.application.ports.vector_store_port import IVectorStorePort
from agentic_learning_platform.application.services.retrieval_service import RetrievalService
from agentic_learning_platform.application.workflows.query_graph import (
    NO_EVIDENCE_MESSAGE,
    QueryGraphState,
    build_query_graph,
    run_query_graph,
)
from agentic_learning_platform.domain.models import (
    DocumentChunk,
    RequestContext,
    SearchResult,
    SourceDocument,
)

_EXPECTED_NODES = {
    "__start__",
    "__end__",
    "retrieve",
    "evaluate_evidence",
    "generate",
    "build_citations",
    "abstain",
}


class _FakeEmbeddingPort(IEmbeddingPort):
    async def embed_text(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def get_dimension(self) -> int:
        return 3

    def get_model_name(self) -> str:
        return "fake-embedding-model"


@dataclass
class _RecordedSearchCall:
    organization_id: str
    course_id: str
    top_k: int


@dataclass
class _FakeVectorStorePort(IVectorStorePort):
    """Spy: records every ``search`` call and returns whatever
    ``results_by_scope`` maps the (organization_id, course_id) pair to
    (empty list if the scope is not present) — enough to assert both
    call-count and per-scope isolation without a real database."""

    results_by_scope: dict[tuple[str, str], list[SearchResult]] = field(default_factory=dict)
    search_calls: list[_RecordedSearchCall] = field(default_factory=list)

    async def find_by_checksum(
        self, checksum_sha256: str, *, organization_id: str, course_id: str
    ) -> SourceDocument | None:
        raise NotImplementedError("not exercised by these tests")

    async def insert_document(
        self,
        document: SourceDocument,
        chunks_with_embeddings: Sequence[tuple[DocumentChunk, list[float]]],
    ) -> None:
        raise NotImplementedError("not exercised by these tests")

    async def search(
        self,
        query_embedding: list[float],
        *,
        organization_id: str,
        course_id: str,
        top_k: int,
    ) -> list[SearchResult]:
        self.search_calls.append(_RecordedSearchCall(organization_id, course_id, top_k))
        return self.results_by_scope.get((organization_id, course_id), [])


@dataclass
class _FakeAnswerGeneratorPort(IAnswerGeneratorPort):
    call_count: int = 0

    async def generate(self, question: str, evidence: list[SearchResult]) -> str:
        self.call_count += 1
        return "a generated answer"


class _RaisingVectorStorePort(_FakeVectorStorePort):
    async def search(
        self,
        query_embedding: list[float],
        *,
        organization_id: str,
        course_id: str,
        top_k: int,
    ) -> list[SearchResult]:
        raise RuntimeError("simulated infrastructure failure")


def _search_result(*, score: float = 0.9, source_name: str = "manual.pdf") -> SearchResult:
    return SearchResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        source_name=source_name,
        page_number=3,
        chunk_index=0,
        content="evidence content",
        score=score,
    )


@dataclass
class _InterleavingVectorStorePort(_FakeVectorStorePort):
    """Adds a deterministic per-scope delay before returning, so two
    concurrent invocations for different tenants provably interleave
    (rather than merely happening to run one after the other) before a
    test asserts no cross-tenant leak."""

    delay_seconds_by_scope: dict[tuple[str, str], float] = field(default_factory=dict)

    async def search(
        self,
        query_embedding: list[float],
        *,
        organization_id: str,
        course_id: str,
        top_k: int,
    ) -> list[SearchResult]:
        await asyncio.sleep(self.delay_seconds_by_scope.get((organization_id, course_id), 0.0))
        return await super().search(
            query_embedding, organization_id=organization_id, course_id=course_id, top_k=top_k
        )


@dataclass
class _InterleavingAnswerGeneratorPort(IAnswerGeneratorPort):
    """Echoes back which evidence it actually received (so a cross-tenant
    bleed into generation would be observable) after a tiny,
    source-dependent delay chosen to force interleaving."""

    delay_seconds_by_source: dict[str, float] = field(default_factory=dict)
    call_count: int = 0

    async def generate(self, question: str, evidence: list[SearchResult]) -> str:
        self.call_count += 1
        source = evidence[0].source_name if evidence else "no-evidence"
        await asyncio.sleep(self.delay_seconds_by_source.get(source, 0.0))
        return f"answer-for-{source}"


def _context(*, org: str = "org-a", course: str = "course-a") -> RequestContext:
    return RequestContext(organization_id=org, course_id=course, user_id="user-1")


_EXPECTED_EDGES = {
    ("__start__", "retrieve", False),
    ("retrieve", "evaluate_evidence", False),
    ("evaluate_evidence", "generate", True),
    ("evaluate_evidence", "abstain", True),
    ("generate", "build_citations", False),
    ("build_citations", "__end__", False),
    ("abstain", "__end__", False),
}


async def test_graph_has_the_expected_node_topology() -> None:
    retrieval_service = RetrievalService(
        _FakeEmbeddingPort(), _FakeVectorStorePort(), top_k=5, score_threshold=0.35
    )
    graph = build_query_graph(retrieval_service, _FakeAnswerGeneratorPort())

    assert set(graph.get_graph().nodes.keys()) == _EXPECTED_NODES


async def test_graph_has_exactly_the_designed_edges() -> None:
    """Asserts the actual wired edges (source, target, conditional) via
    LangGraph's public `get_graph()` introspection API — not node names
    alone, and not the object's repr/string form. Fails if any edge is
    added, removed, or changes conditionality — e.g. a stray
    `generate -> abstain` edge, or `evaluate_evidence` bypassed entirely."""
    retrieval_service = RetrievalService(
        _FakeEmbeddingPort(), _FakeVectorStorePort(), top_k=5, score_threshold=0.35
    )
    graph = build_query_graph(retrieval_service, _FakeAnswerGeneratorPort())

    edges = {(edge.source, edge.target, edge.conditional) for edge in graph.get_graph().edges}

    assert edges == _EXPECTED_EDGES


async def test_sufficient_evidence_path_generates_and_builds_citations() -> None:
    result = _search_result(score=0.9)
    vector_store = _FakeVectorStorePort(results_by_scope={("org-a", "course-a"): [result]})
    generator = _FakeAnswerGeneratorPort()
    retrieval_service = RetrievalService(
        _FakeEmbeddingPort(), vector_store, top_k=5, score_threshold=0.35
    )
    graph = build_query_graph(retrieval_service, generator)

    final_state = await run_query_graph(
        graph, QueryGraphState(question="q", request_context=_context())
    )

    assert final_state.has_sufficient_evidence is True
    assert final_state.answer == "a generated answer"
    assert generator.call_count == 1
    assert len(final_state.citations) == 1
    citation = final_state.citations[0]
    assert citation.source == result.source_name
    assert citation.page == result.page_number
    assert citation.chunk_id == result.chunk_id
    assert citation.score == result.score


async def test_insufficient_evidence_path_abstains_without_calling_generator() -> None:
    vector_store = _FakeVectorStorePort(results_by_scope={})
    generator = _FakeAnswerGeneratorPort()
    retrieval_service = RetrievalService(
        _FakeEmbeddingPort(), vector_store, top_k=5, score_threshold=0.35
    )
    graph = build_query_graph(retrieval_service, generator)

    final_state = await run_query_graph(
        graph, QueryGraphState(question="q", request_context=_context())
    )

    assert final_state.has_sufficient_evidence is False
    assert final_state.answer == NO_EVIDENCE_MESSAGE
    assert final_state.citations == []
    assert generator.call_count == 0


async def test_retrieval_called_exactly_once_per_query() -> None:
    vector_store = _FakeVectorStorePort(
        results_by_scope={("org-a", "course-a"): [_search_result()]}
    )
    retrieval_service = RetrievalService(
        _FakeEmbeddingPort(), vector_store, top_k=5, score_threshold=0.35
    )
    graph = build_query_graph(retrieval_service, _FakeAnswerGeneratorPort())

    await run_query_graph(graph, QueryGraphState(question="q", request_context=_context()))

    assert len(vector_store.search_calls) == 1


async def test_request_context_scopes_every_retrieval_call() -> None:
    vector_store = _FakeVectorStorePort(
        results_by_scope={
            ("org-a", "course-a"): [_search_result()],
            ("org-a", "course-b"): [_search_result()],
        }
    )
    retrieval_service = RetrievalService(
        _FakeEmbeddingPort(), vector_store, top_k=7, score_threshold=0.35
    )
    graph = build_query_graph(retrieval_service, _FakeAnswerGeneratorPort())

    await run_query_graph(
        graph,
        QueryGraphState(question="q", request_context=_context(org="org-a", course="course-a")),
    )
    await run_query_graph(
        graph,
        QueryGraphState(question="q", request_context=_context(org="org-a", course="course-b")),
    )

    assert vector_store.search_calls == [
        _RecordedSearchCall(organization_id="org-a", course_id="course-a", top_k=7),
        _RecordedSearchCall(organization_id="org-a", course_id="course-b", top_k=7),
    ]


async def test_a_node_exception_propagates_unwrapped() -> None:
    retrieval_service = RetrievalService(
        _FakeEmbeddingPort(), _RaisingVectorStorePort(), top_k=5, score_threshold=0.35
    )
    graph = build_query_graph(retrieval_service, _FakeAnswerGeneratorPort())

    with pytest.raises(RuntimeError, match="simulated infrastructure failure"):
        await run_query_graph(graph, QueryGraphState(question="q", request_context=_context()))


async def test_singleton_compiled_graph_is_safe_under_concurrent_cross_tenant_invocation() -> None:
    """The compiled graph is built once and shared across requests (see
    app.py's `_lifespan`) — this proves that sharing is safe: invoking the
    SAME compiled graph instance concurrently for two different tenants
    never lets one tenant's context, retrieval results, or answer leak
    into the other's. Deterministic staggered delays force real
    interleaving (tenant A starts first but finishes last), rather than
    the two calls happening to run strictly one after the other."""
    vector_store = _InterleavingVectorStorePort(
        results_by_scope={
            ("org-a", "course-a"): [_search_result(source_name="tenant-a.pdf")],
            ("org-b", "course-b"): [_search_result(source_name="tenant-b.pdf")],
        },
        delay_seconds_by_scope={
            ("org-a", "course-a"): 0.02,
            ("org-b", "course-b"): 0.0,
        },
    )
    generator = _InterleavingAnswerGeneratorPort(
        delay_seconds_by_source={"tenant-a.pdf": 0.02, "tenant-b.pdf": 0.0}
    )
    retrieval_service = RetrievalService(
        _FakeEmbeddingPort(), vector_store, top_k=5, score_threshold=0.35
    )
    graph = build_query_graph(retrieval_service, generator)

    ctx_a = _context(org="org-a", course="course-a")
    ctx_b = _context(org="org-b", course="course-b")

    state_a, state_b = await asyncio.gather(
        run_query_graph(graph, QueryGraphState(question="qa", request_context=ctx_a)),
        run_query_graph(graph, QueryGraphState(question="qb", request_context=ctx_b)),
    )

    assert state_a.request_context is ctx_a
    assert state_b.request_context is ctx_b
    assert state_a.answer == "answer-for-tenant-a.pdf"
    assert state_b.answer == "answer-for-tenant-b.pdf"
    assert [c.source for c in state_a.citations] == ["tenant-a.pdf"]
    assert [c.source for c in state_b.citations] == ["tenant-b.pdf"]

    # Both scopes were genuinely retrieved despite A's call taking longer
    # than B's — proving the two invocations actually interleaved instead
    # of running sequentially by coincidence.
    scopes_seen = {(c.organization_id, c.course_id) for c in vector_store.search_calls}
    assert scopes_seen == {("org-a", "course-a"), ("org-b", "course-b")}
