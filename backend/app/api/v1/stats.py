from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.checks import StatsOverview
from app.services.check_service import get_overview

router = APIRouter(tags=["stats"])


@router.get("/stats/overview")
def stats_overview(db: Annotated[Session, Depends(get_db)]) -> StatsOverview:
    return get_overview(db)
