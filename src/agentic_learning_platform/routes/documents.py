"""``POST /v1/documents`` — upload and synchronously ingest a PDF."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel

from agentic_learning_platform.application.services.ingestion_service import IngestionService
from agentic_learning_platform.domain.models import RequestContext
from agentic_learning_platform.routes.authorization import get_request_context

router = APIRouter(tags=["documents"])


class DocumentIngestionResponse(BaseModel):
    document_id: UUID
    pages: int
    chunks_created: int
    already_existed: bool


def get_ingestion_service(request: Request) -> IngestionService:
    return request.app.state.ingestion_service


@router.post("/v1/documents", response_model=DocumentIngestionResponse)
async def upload_document(
    file: Annotated[UploadFile, File()],
    ingestion_service: Annotated[IngestionService, Depends(get_ingestion_service)],
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> DocumentIngestionResponse:
    content = await file.read()
    outcome = await ingestion_service.ingest(
        content,
        filename=file.filename or "document.pdf",
        mime_type=file.content_type or "application/octet-stream",
        context=context,
    )
    return DocumentIngestionResponse(
        document_id=outcome.document_id,
        pages=outcome.pages,
        chunks_created=outcome.chunks_created,
        already_existed=outcome.already_existed,
    )
