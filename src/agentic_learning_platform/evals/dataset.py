"""The golden dataset: a small, versioned set of questions with a known,
structurally-verifiable expected outcome — used to measure (never tune)
retrieval/citation/no-evidence quality (see docs/architecture.md's PR-005
section).

Cases are identified by `expected_source` + `expected_pages`, never by
`chunk_id`: chunk ids are `uuid4()`-generated at ingestion time (see
`application.services.ingestion_service.IngestionService.ingest`) and are
not stable across the deterministic re-ingestion this harness performs on
every run (see `runner.py`) — pinning the dataset to them would make it
fragile for no benefit, since source/page is already the same stable
identity the rest of this codebase's tests use (e.g. `test_query_endpoint.py`).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

GOLDEN_DATASET_PATH = Path("eval_data") / "golden_dataset.v1.json"

KNOWN_CATEGORY_PREFIXES = frozenset("ABCDEFGH")


@dataclass(frozen=True, slots=True)
class GoldenCase:
    id: str
    organization_id: str
    course_id: str
    question: str
    expected_answerable: bool
    expected_source: str | None = None
    expected_pages: list[int] = field(default_factory=list[int])
    category: str = ""


class GoldenDatasetError(ValueError):
    """The golden dataset file is malformed or internally inconsistent."""


def load_golden_dataset(path: Path = GOLDEN_DATASET_PATH) -> list[GoldenCase]:
    raw = json.loads(path.read_text())
    cases = [GoldenCase(**item) for item in raw]
    _validate(cases)
    return cases


def _validate(cases: list[GoldenCase]) -> None:
    if not cases:
        raise GoldenDatasetError("golden dataset is empty")

    ids = [case.id for case in cases]
    duplicates = {case_id for case_id in ids if ids.count(case_id) > 1}
    if duplicates:
        raise GoldenDatasetError(f"duplicate case id(s): {sorted(duplicates)}")

    for case in cases:
        if case.expected_answerable and not case.expected_source:
            raise GoldenDatasetError(
                f"case {case.id!r}: expected_answerable=true requires expected_source"
            )
        if case.expected_answerable and not case.expected_pages:
            raise GoldenDatasetError(
                f"case {case.id!r}: expected_answerable=true requires expected_pages"
            )
        if not case.category.strip():
            raise GoldenDatasetError(f"case {case.id!r}: category must not be blank")
        prefix = case.category.split("-", 1)[0]
        if prefix not in KNOWN_CATEGORY_PREFIXES:
            raise GoldenDatasetError(
                f"case {case.id!r}: category {case.category!r} has an unknown prefix "
                f"{prefix!r} (expected one of {sorted(KNOWN_CATEGORY_PREFIXES)})"
            )
