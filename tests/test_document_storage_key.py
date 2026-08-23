import uuid

from agentic_learning_platform.application.ports.document_storage_port import (
    build_document_storage_key,
)


def test_key_is_deterministic_for_the_same_identity() -> None:
    document_id = uuid.uuid4()

    key_a = build_document_storage_key(
        organization_id="org-1", course_id="course-1", document_id=document_id
    )
    key_b = build_document_storage_key(
        organization_id="org-1", course_id="course-1", document_id=document_id
    )

    assert key_a == key_b


def test_key_is_scoped_by_organization_and_course() -> None:
    document_id = uuid.uuid4()

    key = build_document_storage_key(
        organization_id="org-1", course_id="course-1", document_id=document_id
    )

    assert key == f"org/org-1/courses/course-1/documents/{document_id}/source.pdf"


def test_key_differs_across_organizations_for_the_same_document_id() -> None:
    document_id = uuid.uuid4()

    key_org_1 = build_document_storage_key(
        organization_id="org-1", course_id="course-1", document_id=document_id
    )
    key_org_2 = build_document_storage_key(
        organization_id="org-2", course_id="course-1", document_id=document_id
    )

    assert key_org_1 != key_org_2
