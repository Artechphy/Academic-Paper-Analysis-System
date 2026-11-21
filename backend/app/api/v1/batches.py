from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.db.models import RuleSet
from app.db.session import get_db
from app.schemas.checks import BatchDetail, BatchSummary, Verdict
from app.services import check_service
from app.services.paper_service import upload_name

router = APIRouter(tags=["batches"])


@router.post("/batches/check", status_code=status.HTTP_201_CREATED)
def check_batch(
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile], File(min_length=1)],
    rule_set_id: Annotated[UUID, Form()],
    batch_name: Annotated[str | None, Form(max_length=128)] = None,
) -> BatchDetail:
    try:
        uploads = [(upload_name(upload.filename), upload.file) for upload in files]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with db.begin():
        if db.get(RuleSet, rule_set_id) is None:
            raise HTTPException(status_code=404, detail="规则模板不存在")
        return check_service.create_batch(db, rule_set_id, (batch_name or "").strip() or "批量检测", uploads)


@router.get("/batches")
def list_batches(db: Annotated[Session, Depends(get_db)]) -> list[BatchSummary]:
    return check_service.list_batches(db)


@router.get("/batches/{batch_id}")
def get_batch(
    batch_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    verdict: Verdict | None = None,
    q: Annotated[str | None, Query(max_length=255)] = None,
) -> BatchDetail:
    result = check_service.get_batch(db, batch_id, verdict, q.strip() if q else None)
    if result is None:
        raise HTTPException(status_code=404, detail="检测批次不存在")
    return result
