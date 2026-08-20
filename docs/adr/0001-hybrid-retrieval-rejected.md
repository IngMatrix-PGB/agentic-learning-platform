# ADR-0001 — Hybrid Retrieval Experiment Rejected

## Status

Rejected

## Context

PR-005 established a reproducible vector-only baseline using a dedicated
evaluation harness (golden dataset, fixed metrics, dedicated eval database).

Baseline (`eval_results/baseline_vector_only.v1.json`):

- Recall@1 = 0.846154
- Recall@3 = 0.961538
- Recall@5 = 0.961538
- MRR = 0.903846
- Citation Accuracy = 0.961538
- No-Evidence Accuracy = 1.0
- FPR = 0.0
- FNR = 0.0

## Hypothesis

Combining:

- Vector Search
- PostgreSQL Full Text Search
- Reciprocal Rank Fusion (RRF)

would improve Recall/MRR/Citation Accuracy over vector-only, without
degrading isolation, latency (within reason), or the no-evidence behavior.

## Method

- Same golden dataset as PR-005 (`eval_data/golden_dataset.v1.json`),
  unmodified.
- Same metric formulas as PR-005, unmodified.
- Same embeddings, same chunking, same evidence threshold.
- RRF k = 60 (literature-standard default, not tuned).
- candidate_top_k = 15 per branch, final_top_k = retrieval_top_k (5).
- No tuning of any parameter after observing results.
- organization_id/course_id isolation preserved and adversarially tested
  across every branch (vector, lexical, fused).

## Result

The hybrid strategy produced **exactly the same quality metrics** as the
vector-only baseline (`eval_results/hybrid_retrieval.v1.json`):

- Recall@1 = 0.846154 (no change)
- Recall@3 = 0.961538 (no change)
- Recall@5 = 0.961538 (no change)
- MRR = 0.903846 (no change)
- Citation Accuracy = 0.961538 (no change)
- No-Evidence Accuracy = 1.0 (no change)
- FPR = 0.0 (no change)
- FNR = 0.0 (no change)

There was no improvement in Recall@1, Recall@3, Recall@5, MRR, or Citation
Accuracy.

There was an increase of approximately **+43% in p95 retrieval latency**
(8.07ms → 11.43ms; mean 5.65ms → 8.09ms), plus additional production
complexity that would have been introduced:

- a new lexical search port (`ILexicalSearchPort`)
- a new lexical search adapter (`PostgresLexicalSearchAdapter`)
- a new PostgreSQL full-text-search index (migration)
- Reciprocal Rank Fusion logic
- a new retrieval-strategy configuration/wiring surface
- a hybrid-specific evidence-sufficiency code path

See `eval_results/comparison_vector_vs_hybrid.v1.json` for the full,
per-case comparison.

## Root cause / observation

`C1-sla-synonym` was not retrieved correctly by either vector search or
PostgreSQL FTS. Its question was deliberately phrased (in PR-005) by
semantic intent, specifically to minimize lexical overlap with its source
text — the same property that made it a genuine test of vector search's
weakness also removed the term overlap that PostgreSQL FTS depends on.
As a result, RRF had no additional useful lexical signal to fuse: fusing
two rankings that both miss the correct document cannot produce it.

`C2-support-tiers-synonym`, `D1-incident-ambiguous`, and
`D2-problem-ambiguous` were present among the candidates in both the
vector-only and hybrid runs, at the same rank (2) in both — a different
problem (ranking/ordering among already-retrieved candidates), not a
recall problem. RRF did not change their order either, in this dataset.

## Decision

**KEEP VECTOR_ONLY.**

The hybrid retrieval runtime (port, adapter, migration, RRF, strategy
wiring, hybrid evidence logic) is **not** incorporated into `main`. Only
the experimental evidence and a generic comparison tool are retained (see
"Evidence" below and the file tree of this PR).

## Consequences

- Production retrieval remains exactly as it was after PR-005: a single
  vector-only code path, no strategy flag, no lexical index.
- No PostgreSQL FTS migration in `main`.
- No lexical search port/adapter in `main`.
- No RRF runtime code in `main`.
- The vector-only baseline remains the official retrieval strategy.
- The experimental evidence is preserved (this ADR, the two eval-result
  JSON files, and the `feat/pr-006-hybrid-retrieval` branch) specifically
  so this exact experiment is not repeated without cause.

## Reranking note

Reranking could plausibly improve `C2`/`D1`/`D2`, because the correct
document is already present among the retrieved candidates in those cases
— reranking only needs to reorder it upward.

Reranking would **not** resolve `C1`, because the correct evidence is not
present in the retrieved candidates at all in either branch. A reranker
can only reorder what retrieval already found; it cannot recover a
document that was never retrieved.

## Licensing finding

FastEmbed 0.8.0, already installed locally, exposes ONNX-based reranking
(`fastembed.rerank.cross_encoder.TextCrossEncoder`) without requiring
PyTorch on the reranking path.

However, the only multilingual model available in FastEmbed's supported
list (`jinaai/jina-reranker-v2-base-multilingual`) is licensed
**CC-BY-NC-4.0** (non-commercial). The remaining supported reranker models
are permissively licensed (Apache-2.0 / MIT) but English-only, unsuited to
this project's Spanish-language corpus.

This must not be adopted for a commercial product without explicitly
resolving that licensing restriction first. No web research was performed
and no alternative model is proposed in this ADR — this finding is based
solely on local inspection of the already-installed dependency.

## Evidence

- `eval_results/baseline_vector_only.v1.json`
- `eval_results/hybrid_retrieval.v1.json`
- `eval_results/comparison_vector_vs_hybrid.v1.json`
- Historical branch: `feat/pr-006-hybrid-retrieval` (full implementation,
  preserved in `origin`, not merged)
