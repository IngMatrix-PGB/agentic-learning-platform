"""S3-backed source-document storage. Used when ``settings.runtime_mode ==
"aws"``.

Uses plain synchronous ``boto3`` wrapped in ``asyncio.to_thread`` — the same
pattern ``IDocumentParserPort`` implementations already use for CPU-bound
work (see that port's docstring) — rather than adding ``aioboto3`` as a new
dependency for a low-volume, non-hot-path operation (document upload).

Private objects only: no ACL is ever set (default bucket ACL/policy — never
``public-read`` or similar), no presigned URLs are generated here.
"""

import asyncio
import logging

import boto3
from botocore.exceptions import ClientError

from agentic_learning_platform.application.ports.document_storage_port import IDocumentStoragePort
from agentic_learning_platform.config import Settings
from agentic_learning_platform.exceptions import DocumentStorageError

logger = logging.getLogger(__name__)


class S3DocumentStorageAdapter(IDocumentStoragePort):
    def __init__(self, settings: Settings) -> None:
        if not settings.s3_bucket:
            # Startup-time misconfiguration should already have been caught
            # by config.validate_aws_configuration before this adapter is
            # ever constructed — this is a defensive invariant, not the
            # primary check.
            raise DocumentStorageError("S3_BUCKET is not configured for runtime_mode=aws")
        self._bucket = settings.s3_bucket
        self._client = boto3.client("s3", region_name=settings.aws_region)

    async def upload(self, content: bytes, *, key: str, content_type: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
        except ClientError as exc:
            raise DocumentStorageError(f"S3 upload failed for key {key!r}: {exc}") from exc
        logger.info("s3_document_uploaded bucket=%s key=%s", self._bucket, key)

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise DocumentStorageError(f"S3 delete failed for key {key!r}: {exc}") from exc
        logger.info("s3_document_deleted bucket=%s key=%s", self._bucket, key)
