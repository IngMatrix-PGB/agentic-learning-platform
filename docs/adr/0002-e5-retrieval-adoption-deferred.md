# ADR-0002 — Defer E5 Retrieval Adoption Until Evidence Gating Is Reliable

## Status

Deferred

## Context

PR-005 established a reproducible vector-only baseline using the same
evaluation harness ADR-0001 relies on (golden dataset, fixed metrics,
dedicated eval database). That baseline's most significant finding was
`C1-sla-synonym`: a deliberately paraphrased question whose correct evidence
never appears at all in the current embedding model's top-5 — a genuine
recall failure, not a ranking failure (see ADR-0001, which investigated and
rejected a different fix for a related problem: Hybrid Retrieval).

This ADR documents a separate line of experiments (EXP-003 through
EXP-003D) that investigated whether upgrading the embedding model itself —
rather than adding a second retrieval signal — could close that recall gap,
and whether the resulting system could be gated safely enough to serve real
users.

## Current Production Baseline

- Embedding model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Dimension: 384
- Retrieval strategy: vector-only
- Evidence threshold: `retrieval_score_threshold = 0.35`

Official baseline (`eval_results/baseline_vector_only.v1.json`, PR-005):

- Recall@1 = 0.846154
- Recall@3 = 0.961538
- Recall@5 = 0.961538
- MRR = 0.903846

## EXP-003 — E5 Retrieval Quality

Candidate: `intfloat/multilingual-e5-large`, 1024 dimensions, MIT license,
evaluated in an isolated harness (disposable database, `embedding_dimension=1024`,
manual `"query: "`/`"passage: "` prefixing verified against the official
model card — see evidence file for the full methodology notes) against the
exact same golden dataset, corpus, chunking, and metric formulas as the
baseline.

Result (`eval_results/e5_retrieval_ranking.v1.json`):

- Recall@1 = 0.8846
- Recall@3 = 1.0000
- Recall@5 = 1.0000
- MRR = 0.9359

Case-level changes of note:

- `C1-sla-synonym`: unretrieved → rank 3 (the headline recall failure is
  resolved — the correct page now enters the top-3)
- `D1-incident-ambiguous`: rank 2 → rank 1
- `D2-problem-ambiguous`: rank 2 → rank 1
- `B4-cmdb-paraphrase`: rank 1 → rank 2 (one regression, disclosed rather
  than hidden — it does not change Recall@3/5 for that case)

Aggregate case-level breakdown across all 26 answerable golden-dataset
cases:

- 3 improved (`C1-sla-synonym`, `D1-incident-ambiguous`, `D2-problem-ambiguous`)
- 1 regressed (`B4-cmdb-paraphrase`)
- 22 unchanged

By category: the improvement is concentrated in **C-related-terms** (1 of 3
cases) and **D-ambiguous** (2 of 3 cases). Categories A-direct, B-paraphrase,
F-distractor, G-cross-course, and H-cross-org show no improved cases — B
is in fact the source of the one regression, and the other four categories
are entirely unchanged.

Because the D-ambiguous gains and the B-paraphrase regression both affect
Recall@1, the **net** Recall@1 benefit is smaller than "3 improved cases"
suggests: 2 cases newly reach rank 1 (D1, D2), 1 case leaves rank 1 (B4),
for a net gain of **+1 case out of 26** (+0.03846), which is exactly the
observed baseline→E5 Recall@1 delta (0.846154 → 0.884615). Recall@3/5 are
unaffected by B4's regression, since it only drops from rank 1 to rank 2.

**Conclusion: GO — retrieval ranking, on this evaluation corpus.** The
improvement is not an artifact of a single accidental case: it appears
across more than one case and more than one category, with zero cases
losing recall entirely. This is the same discipline ADR-0001 applied when
it rejected adopting Hybrid Retrieval specifically because that improvement
traced back to one case only — E5's improvement does not share that
weakness. It is, however, concentrated in 2 of 7 categories and a small
fraction of cases (3 of 26), so the appropriate claim is scoped to this
corpus, not stated as a general property of E5 as a retriever (see
Decision, below).

## EXP-003B — Absolute Cosine Evidence Threshold

A new, independent 60-question dataset (not the golden dataset, not reused
as a later holdout), split 40 calibration / 20 validation, was used to
search programmatically for a `top1_score` threshold analogous to the
current `retrieval_score_threshold`.

Selected threshold (chosen using calibration only): **0.830029**
(`eval_results/e5_absolute_threshold.v1.json`).

- Calibration: TPR = 90%, FPR = 5%
- Validation: TPR = 90%, **FPR = 30%**

**Conclusion: NO-GO.** The threshold did not generalize — validation FPR is
6x the calibration FPR. The underlying problem: E5 can produce high cosine
similarity for a question that is merely topically related to the corpus,
even when the corpus does not actually contain an answer to it. Topic
similarity is not the same signal as answer presence, and a single absolute
cutoff on cosine similarity conflates the two.

## EXP-003C — Relative Margin Evidence Gate

A second independent dataset (80 questions, 40 answerable / 40 no-evidence,
split 56 calibration / 24 validation) tested whether `margin_12 = top1_score
- top2_score` — "is there a clearly dominant result?" — could succeed where
the absolute threshold failed.

- Calibration TPR = 17.86% (already a weak signal before validation)
- Validation: TPR = 0%, FPR = 8.33%

**Conclusion: NO-GO.** A low margin does not mean insufficient evidence.
Case-level inspection showed correct top-1 results with near-zero margin
simply because this corpus contains several thematically adjacent chunks
(incident management, problem management, and change management all share
vocabulary) — a semantically dense corpus produces close top1/top2 scores
even when top1 is the right answer. Optimizing for a large margin would
have penalized genuinely correct retrievals, not rescued incorrect ones.

## EXP-003D — Cross-Encoder Evidence Verifier

A third, independent dataset (120 `(question, candidate_passage,
expected_label)` pairs, 60 SUPPORTED / 60 UNSUPPORTED, split 85 calibration
/ 35 validation) tested whether a
cross-encoder (`BAAI/bge-reranker-v2-m3`, the same FP32 ONNX artifact
already verified for provenance in the reranking line of experiments) could
verify — per candidate, not per ranking — whether a passage actually
supports a question.

Selected threshold (raw logit, calibration only): **-0.595370**
(`eval_results/e5_cross_encoder_verifier.v1.json`).

- Calibration: TPR = 61.36%, FPR = 2.44%
- Validation: TPR = 43.75%, FPR = 15.79%, balanced accuracy = 63.98%

**Conclusion: NO-GO — cross-encoder verifier not reliable.** All three GO
criteria (FPR ≤ 5%, TPR ≥ 90%, balanced accuracy ≥ 90%) failed on
validation. A direct diagnostic against the actual headline cases (C1, C2,
D1, D2, B4) showed the verifier would have rejected the correct evidence in
every one of them — this specific approach would have made those cases
worse, not better, had it been deployed as calibrated.

## Common Failure Pattern

Three independent evidence-gating families were tested:

1. Absolute vector similarity (EXP-003B)
2. Relative vector geometry / margin (EXP-003C)
3. Semantic cross-encoder verification (EXP-003D)

None generalized under the criteria fixed in advance for each. The common
pattern: whatever rule keeps false positives low enough also ends up
rejecting too many genuinely answerable questions once those questions are
phrased indirectly, paraphrased, or fall in a semantically dense region of
the corpus — exactly the style of question this project's own golden
dataset (and each experiment's independent dataset) was built to contain.

## Decision

**DEFER E5 ADOPTION.**

Two distinct claims must not be conflated:

> "E5 demonstrated better retrieval ranking on this evaluation corpus." —
> **supported** by EXP-003 (see the case-level breakdown above; this is a
> corpus-scoped observation, not a general claim about E5 as a retriever).

> "E5 is safe to adopt end-to-end." — **not supported** by EXP-003B/C/D.

Because the second claim is unresolved, the production runtime does not
change:

- Embedding model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Dimension: 384
- Strategy: vector-only
- Evidence threshold: `0.35`

## Why Deferred Rather Than Rejected

E5 produced real, measured improvements: Recall@1 +3.85 percentage points
(approximately), Recall@3/5 reaching 100%, MRR +3.2 percentage points
(approximately). This is not a rejected hypothesis in the sense ADR-0001's
Hybrid Retrieval was (which showed **zero** measurable improvement on every
quality metric). The blocker here is specifically evidence gating, not
retrieval quality — a narrower, more tractable problem than "E5 doesn't
help," which is why this is recorded as deferred pending a reliable
answerability signal, not rejected outright.

## Operational Observations (not the primary reason for deferral)

Observed during the EXP-003 session, in an experimental harness — **not** a
production benchmark, and **not captured in any versioned benchmark
artifact** (none of the JSON files under Evidence contain latency or memory
fields; these numbers come from the session record only, and are not
independently reproducible from the committed evidence package alone):

- ~2.1 GB model/cache size
- ~1.57 GB additional RSS
- ~112 s initial cold download/load
- ~2.47 s warm load
- Retrieval approximately 8-9x slower than the current baseline while
  remaining sub-100 ms in that experimental run

These costs are real and would need production-grade measurement before
any adoption, but they were **not** the reason for deferral — the evidence
gating failure alone would have blocked adoption even if these costs were
zero.

## Consequences

**Positive:**
- Current runtime remains simple — one embedding model, one dimension, no
  new evidence-gating logic to maintain or reason about.
- No 384 → 1024 migration, no reindexing of existing production data.
- No new ~2.1 GB model dependency added to the runtime image.
- No unvalidated evidence gate shipped to users.
- The committed evidence package preserves the frozen evaluation inputs,
  raw experimental scores, and derived reports required to audit the
  reported decisions and threshold-selection procedure (see Evidence,
  below). It does not preserve the complete experimental execution
  environment (harness scripts, downloaded model artifacts, disposable
  databases) — see Evidence for the explicit boundary.

**Negative:**
- The current runtime retains `C1`-like recall limitations — a class of
  paraphrased question whose evidence is not retrieved at all can still
  occur.
- E5's demonstrated ranking improvements are not captured in production.
- Reliable answerability / evidence-sufficiency detection for a semantically
  dense corpus remains an open, unsolved problem — not just for E5, but
  potentially for any future retrieval upgrade with a similarly shaped
  score distribution.

## Conditions for Revisiting E5

Re-opening this investigation "because we can keep experimenting" is not
sufficient justification. Revisiting E5 (or any embedding upgrade) should
require at least one of:

- A materially larger, real-world (non-synthetic) dataset that can support
  a properly powered calibration/validation split.
- A real client or pilot corpus, where the actual density/overlap of topics
  can be observed directly rather than assumed from a small synthetic
  corpus.
- Evidence that `C1`-like recall failures are common or material in real
  usage, not just a single constructed adversarial case.
- A domain-specific answerability/evidence verifier validated independently
  of this line of experiments.
- A validated LLM-based answerability or groundedness approach (not
  attempted here — this ADR's experiments were deliberately non-LLM, per
  the constraints of EXP-003B/C/D).
- A fundamentally different abstention architecture (e.g., one that does
  not rely on a single scalar threshold/margin/logit decision at all).
- A materially different retrieval or evidence model whose score
  distribution does not exhibit the same topic-similarity-vs-answer-presence
  conflation observed here.

## Relationship with Future LangGraph Orchestration

**LangGraph does not solve evidence quality.** `docs/OPEN_SOURCE_DISCOVERY.md`
already documents LangGraph + `langgraph-checkpoint-postgres` as an approved
architectural direction for a future orchestration PR. A future graph might
represent the flow as:

```
Resolve Context
  -> Retrieve
  -> Evaluate Evidence
      -> insufficient -> Abstain
      -> sufficient -> Generate
  -> Validate Citations
  -> Response
```

LangGraph would only orchestrate that flow — the `Evaluate Evidence` node's
actual policy still needs to be a validated decision function, independent
of whichever framework calls it. Nothing in this ADR's findings changes
that node's implementation today (it remains the existing
`retrieval_score_threshold = 0.35` check), and nothing about adopting
LangGraph resolves the open evidence-gating problem documented here.
**Therefore, this ADR does not block a future LangGraph orchestration PR.**

## Evidence

The committed evidence package preserves the frozen evaluation inputs,
raw experimental scores, and derived aggregate reports required to audit
the reported decisions and threshold-selection procedure. It does not
preserve the complete experimental execution environment.

**Preserved / auditable from Git:**

`eval_data/` — frozen evaluation inputs (question sets, fixed before any
score was observed):

- `golden_dataset.v1.json` (PR-005, unchanged — EXP-003's baseline/E5
  comparison)
- `e5_threshold_calibration_dataset.v1.json` (EXP-003B's 60-question
  calibration/validation dataset)
- `e5_margin_gate_dataset.v1.json` (EXP-003C's 80-question
  calibration/validation dataset)
- `e5_verifier_dataset.v1.json` (EXP-003D's 120 `(question,
  candidate_passage, expected_label)` pairs)

`eval_results/` — raw per-item scores and derived aggregate reports:

- `baseline_vector_only.v1.json` (PR-005, unchanged)
- `e5_retrieval_ranking.v1.json` (EXP-003 aggregate + case-by-case)
- `e5_absolute_threshold.v1.json` (EXP-003B aggregate report)
- `e5_threshold_scores.v1.json` (EXP-003B raw per-question `top1_score`/
  `top2_score`/margin used to select the threshold)
- `e5_margin_gate.v1.json` (EXP-003C aggregate report)
- `e5_margin_gate_scores.v1.json` (EXP-003C raw per-question
  `s1`/`s2`/`s3`/`margin_12` used to select the threshold)
- `e5_cross_encoder_verifier.v1.json` (EXP-003D aggregate report)
- `e5_verifier_scores.v1.json` (EXP-003D raw per-pair cross-encoder
  logits used to select the threshold)

These datasets and raw scores are preserved specifically because they are
what let a reader independently re-run the threshold-selection algorithm
(candidates = calibration scores and midpoints, qualify at FPR ≤ 5%,
choose max TPR) restricted to `split == "calibration"` rows and confirm it
reproduces the threshold each report claims — auditing the
calibration/validation separation and the "no validation peeking"
property this ADR's conclusions depend on, without relying on this
session's ephemeral scratch directory. They contain synthetic ITSM
evaluation questions/passages only (verified: no customer data, no real
document content, no credentials, no absolute paths).

**Not preserved (deliberately):**

- One-off harness scripts (`run_exp003*.py`, `e5_embedding_harness.py`,
  `score_verifier.py`, `analyze_*.py`) — experimental tooling, not
  production code, not a reusable comparison utility (unlike ADR-0001's
  `compare_reports.py`).
- Downloaded model artifacts (E5 weights, the `bge-reranker-v2-m3` ONNX
  export, tokenizer/model caches).
- The disposable experiment databases and venvs used to run EXP-003
  through EXP-003D.

This mirrors ADR-0001's approach of preserving useful evidence without
preserving dead experimental runtime — extended here to also preserve the
frozen datasets and raw scores needed to audit *how* each threshold was
selected, not just the resulting aggregate numbers. Re-running the E5
experiments end-to-end still requires reconstructing the harness and
downloading the model artifacts; that reconstruction is not what this
evidence package provides.
