from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Paper, RuleSet
from app.db.session import get_db
from app.schemas.checks import CheckRunDetail, RecheckRequest
from app.services import check_service

router = APIRouter(tags=["papers"])


@router.get("/check-runs/{run_id}")
def get_check_run(run_id: UUID, db: Annotated[Session, Depends(get_db)]) -> CheckRunDetail:
    result = check_service.get_run(db, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="检测记录不存在")
    return result


@router.post("/papers/{paper_id}/recheck", status_code=status.HTTP_201_CREATED)
def recheck(
    paper_id: UUID, request: RecheckRequest, db: Annotated[Session, Depends(get_db)]
) -> CheckRunDetail:
    with db.begin():
        paper = db.get(Paper, paper_id, with_for_update=request.reparse)
        if paper is None:
            raise HTTPException(status_code=404, detail="论文不存在")
        if db.get(RuleSet, request.rule_set_id) is None:
            raise HTTPException(status_code=404, detail="规则模板不存在")
        try:
            return check_service.recheck(db, paper, request.rule_set_id, reparse=request.reparse)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="论文原件不存在。") from exc
