"""Entrypoint: ``uv run python -m agentic_learning_platform.evals.run_eval``
(wrapped by ``make eval`` / ``make eval-hybrid``). Writes
``eval_results/baseline_vector_only.v1.json`` or
``eval_results/hybrid_retrieval.v1.json`` — named after
``settings.retrieval_strategy`` — and prints a human-readable summary. See
docs/architecture.md's PR-005/PR-006 sections for what each field means.

The output path is chosen by strategy specifically so a PR-006 (hybrid) run
writes its own file alongside PR-005's frozen baseline instead of silently
overwriting it.
"""

import asyncio
from pathlib import Path

from agentic_learning_platform.evals import report
from agentic_learning_platform.evals.runner import run

_RESULTS_PATH_BY_STRATEGY = {
    "vector_only": Path("eval_results") / "baseline_vector_only.v1.json",
    "hybrid": Path("eval_results") / "hybrid_retrieval.v1.json",
}


async def _main() -> None:
    eval_run = await run()
    payload = report.build_report(eval_run)

    results_path = _RESULTS_PATH_BY_STRATEGY[eval_run.settings.retrieval_strategy]
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(report.render_json(payload) + "\n")

    print(report.render_summary(payload))
    print(f"\nFull report written to {results_path}")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
