"""Revision workspace API."""
from contextlib import contextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.revisions.latex_annotator import ExportError
from app.schemas.revisions import (
    AnnotatedPdfExportRequest, AnnotatedPdfExportResponse, AutoFixRequest, DocumentSettingsRequest,
    ParagraphEditRequest, ParagraphEditResponse, RevisionSessionDetail,
)
from app.services import revision_service as service

router = APIRouter(tags=["revisions"])
Database = Annotated[Session, Depends(get_db)]


@contextmanager
def _operation(db, *, write=False):
    try:
        if write:
            with db.begin():
                yield
        else:
            yield
    except Exception as exc:
        for path in db.info.pop("revision_artifacts", ()):
            path.unlink(missing_ok=True)
        if isinstance(exc, service.RevisionNotFound):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if isinstance(exc, ExportError):
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise
    finally:
        db.info.pop("revision_artifacts", None)


@router.post("/check-runs/{run_id}/revisions", status_code=201)
def create_revision(run_id: UUID, db: Database, force_new: bool = False) -> RevisionSessionDetail:
    with _operation(db, write=True):
        return service.create(db, run_id, force_new=force_new)


@router.get("/revisions/{session_id}")
def get_revision(session_id: UUID, db: Database) -> RevisionSessionDetail:
    with _operation(db):
        return service.get(db, session_id)


@router.patch("/revisions/{session_id}/paragraphs/{paragraph_index}")
def edit_paragraph(session_id: UUID, paragraph_index: int, request: ParagraphEditRequest,
                   db: Database) -> ParagraphEditResponse:
    with _operation(db, write=True):
        return service.edit(db, session_id, paragraph_index, request)


@router.patch("/revisions/{session_id}/document-settings")
def document_settings(session_id: UUID, request: DocumentSettingsRequest, db: Database) -> RevisionSessionDetail:
    with _operation(db, write=True):
        return service.document_settings(db, session_id, request)


@router.post("/revisions/{session_id}/auto-fix")
def auto_fix(session_id: UUID, db: Database, request: AutoFixRequest | None = None) -> RevisionSessionDetail:
    with _operation(db, write=True):
        return service.auto_fix(db, session_id, request or AutoFixRequest())


@router.post("/revisions/{session_id}/export/annotated-pdf")
def export_pdf(session_id: UUID, db: Database,
               request: AnnotatedPdfExportRequest | None = None) -> AnnotatedPdfExportResponse:
    with _operation(db, write=True):
        return service.export_pdf(db, session_id, (request or AnnotatedPdfExportRequest()).page_mode)


@router.get("/revisions/{session_id}/download/{kind}")
def download(session_id: UUID, kind: Literal["docx", "annotated_pdf"], db: Database) -> FileResponse:
    with _operation(db):
        path, name = service.download(db, session_id, kind)
        mime = "application/pdf" if kind == "annotated_pdf" else (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        return FileResponse(path, media_type=mime, filename=name)
