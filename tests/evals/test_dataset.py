"""Schema/consistency tests for the golden dataset file itself — fast, no
DB, no retrieval. Confirms the shipped `golden_dataset.v1.json` is
well-formed; does not assert anything about retrieval quality (that is
`make eval`'s job, not pytest's — see docs/architecture.md's PR-005
section).
"""

import json
from pathlib import Path

import pytest

from agentic_learning_platform.evals.dataset import (
    GOLDEN_DATASET_PATH,
    KNOWN_CATEGORY_PREFIXES,
    GoldenDatasetError,
    load_golden_dataset,
)


def test_shipped_dataset_loads_and_validates() -> None:
    cases = load_golden_dataset()

    assert 20 <= len(cases) <= 40


def test_shipped_dataset_has_at_least_one_case_per_required_category() -> None:
    cases = load_golden_dataset()
    prefixes = {case.category.split("-", 1)[0] for case in cases}

    assert prefixes >= KNOWN_CATEGORY_PREFIXES


def test_shipped_dataset_has_no_blank_category() -> None:
    cases = load_golden_dataset()

    assert all(case.category.strip() for case in cases)


def test_shipped_dataset_has_exactly_the_documented_duplicate_questions() -> None:
    """32 cases, 28 unique question formulations — three groups
    intentionally reuse question text (see docs/architecture.md's PR-005
    section):

    - G1/G2 (and, incidentally, A1) all ask "¿Qué es la gestión de
      incidentes?" — G1/G2 *must* share text by design (a cross-course pair
      asks the identical question against two scopes); A1 additionally
      landing on the same natural phrasing was not required and is the one
      avoidable overlap flagged in code review.
    - G3/G4 share a paraphrase, by the same cross-course pairing design.
    - H1/H2 share a question, by the equivalent cross-organization pairing
      design.

    This pins down that these three groups are the *only* duplication —
    `num_cases` (32) must never be quietly read as 32 unique formulations,
    but a new, undocumented duplicate should fail this test rather than
    pass silently.
    """
    cases = load_golden_dataset()
    questions = [case.question for case in cases]
    duplicated_questions = {q for q in questions if questions.count(q) > 1}

    duplicate_groups = sorted(
        sorted(c.id for c in cases if c.question == question) for question in duplicated_questions
    )

    assert duplicate_groups == [
        ["A1-incident-direct", "G1-crosscourse-101-literal", "G2-crosscourse-201-literal"],
        ["G3-crosscourse-101-paraphrase", "G4-crosscourse-201-paraphrase"],
        ["H1-crossorg-primary", "H2-crossorg-secondary"],
    ]
    assert len(questions) - len(set(questions)) == 4  # 32 cases, 28 unique questions


def test_shipped_dataset_has_at_least_one_unanswerable_case() -> None:
    cases = load_golden_dataset()

    assert any(not case.expected_answerable for case in cases)


def test_shipped_dataset_spans_more_than_one_organization_and_course() -> None:
    cases = load_golden_dataset()

    assert len({case.organization_id for case in cases}) >= 2
    assert len({case.course_id for case in cases}) >= 2


def test_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    raw = json.loads(GOLDEN_DATASET_PATH.read_text())
    duplicated = raw[:1] + raw[:1] + raw[1:]
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(duplicated))

    with pytest.raises(GoldenDatasetError):
        load_golden_dataset(dataset_path)


def test_rejects_an_answerable_case_missing_expected_source(tmp_path: Path) -> None:
    raw = [
        {
            "id": "broken",
            "organization_id": "org",
            "course_id": "course",
            "question": "¿?",
            "expected_answerable": True,
        }
    ]
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(raw))

    with pytest.raises(GoldenDatasetError):
        load_golden_dataset(dataset_path)


def test_rejects_an_empty_dataset(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("[]")

    with pytest.raises(GoldenDatasetError):
        load_golden_dataset(dataset_path)


@pytest.mark.parametrize("blank_category", ["", "   "])
def test_rejects_a_blank_category(tmp_path: Path, blank_category: str) -> None:
    raw = [
        {
            "id": "broken",
            "organization_id": "org",
            "course_id": "course",
            "question": "¿?",
            "expected_answerable": False,
            "category": blank_category,
        }
    ]
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(raw))

    with pytest.raises(GoldenDatasetError, match="blank"):
        load_golden_dataset(dataset_path)


def test_rejects_an_unknown_category_prefix(tmp_path: Path) -> None:
    raw = [
        {
            "id": "broken",
            "organization_id": "org",
            "course_id": "course",
            "question": "¿?",
            "expected_answerable": False,
            "category": "Z-not-a-real-category",
        }
    ]
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(raw))

    with pytest.raises(GoldenDatasetError, match="unknown prefix"):
        load_golden_dataset(dataset_path)
