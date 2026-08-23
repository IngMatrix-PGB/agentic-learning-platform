"""Opt-in (see conftest.py): validates real S3 upload/read-back/delete
against the configured ``S3_BUCKET`` — a real object, not a mocked
``boto3`` client.
"""

import uuid

import boto3
from botocore.exceptions import ClientError

from agentic_learning_platform.application.ports.document_storage_port import (
    build_document_storage_key,
)
from agentic_learning_platform.config import Settings
from agentic_learning_platform.infrastructure.storage.s3_document_storage_adapter import (
    S3DocumentStorageAdapter,
)


async def test_s3_upload_then_delete_round_trip(aws_smoke_settings: Settings) -> None:
    settings = aws_smoke_settings
    adapter = S3DocumentStorageAdapter(settings)
    key = build_document_storage_key(
        organization_id="aws-smoke-test",
        course_id="aws-smoke-test",
        document_id=uuid.uuid4(),
    )
    content = b"%PDF-1.4 aws smoke test content"

    await adapter.upload(content, key=key, content_type="application/pdf")

    s3_client = boto3.client("s3", region_name=settings.aws_region)
    head = s3_client.head_object(Bucket=settings.s3_bucket, Key=key)
    assert head["ContentLength"] == len(content)

    await adapter.delete(key)

    still_there = True
    try:
        s3_client.head_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError:
        still_there = False
    assert not still_there, "object should no longer exist after delete"
