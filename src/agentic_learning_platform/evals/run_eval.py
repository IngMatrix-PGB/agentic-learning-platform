"""Entrypoint: ``uv run python -m agentic_learning_platform.evals.run_eval``
(wrapped by ``make eval``). Writes ``eval_results/baseline_vector_only.v1.json``
and prints a human-readable summary — see docs/architecture.md's PR-005
section for what each field means and how PR-006 is expected to reuse this.

The output path is named after the retrieval strategy it measures
(``baseline_vector_only.v1.json``), not a generic ``eval_results.json`` —
a future PR-006 (Hybrid Retrieval) run writes its own
``eval_results/hybrid_retrieval.v1.json`` alongside this one instead of
silently overwriting PR-005's baseline.
"""

import asyncio
from pathlib import Path

from agentic_learning_platform.evals import report
from agentic_learning_platform.evals.runner import run

RESULTS_PATH = Path("eval_results") / "baseline_vector_only.v1.json"


async def _main() -> None:
    eval_run = await run()
    payload = report.build_report(eval_run)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(report.render_json(payload) + "\n")

    print(report.render_summary(payload))
    print(f"\nFull report written to {RESULTS_PATH}")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
