from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import RuleItem, RuleSet
from app.db.session import get_db
from app.schemas.rules import (
    RuleItemResponse,
    RuleItemUpdate,
    RuleSetCreate,
    RuleSetDetail,
    RuleSetResponse,
    validate_rule_params,
)
from app.services.check_service import rule_items_query

router = APIRouter(tags=["rules"])

_RULE_COUNT = (
    select(func.count(RuleItem.id))
    .where(RuleItem.rule_set_id == RuleSet.id)
    .correlate(RuleSet)
    .scalar_subquery()
    .label("rule_count")
)


@router.get("/rule-sets")
def list_rule_sets(db: Annotated[Session, Depends(get_db)]) -> list[RuleSetResponse]:
    rows = db.execute(
        select(RuleSet.__table__, _RULE_COUNT).order_by(
            RuleSet.is_default.desc(), RuleSet.code, RuleSet.version
        )
    ).mappings()
    return [RuleSetResponse.model_validate(row) for row in rows]


def _rule_set_detail(db: Session, rule_set_id: UUID) -> RuleSetDetail:
    row = db.execute(
        select(RuleSet.__table__, _RULE_COUNT).where(RuleSet.id == rule_set_id)
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="规则模板不存在")
    items = db.scalars(rule_items_query(rule_set_id)).all()
    return RuleSetDetail(**row, rule_items=items)


@router.get("/rule-sets/{rule_set_id}")
def get_rule_set(rule_set_id: UUID, db: Annotated[Session, Depends(get_db)]) -> RuleSetDetail:
    return _rule_set_detail(db, rule_set_id)


@router.post("/rule-sets", status_code=status.HTTP_201_CREATED)
def create_rule_set(request: RuleSetCreate, db: Annotated[Session, Depends(get_db)]) -> RuleSetDetail:
    fields = request.model_dump(exclude={"rule_items", "source_rule_set_id"})
    try:
        with db.begin():
            if request.source_rule_set_id is not None:
                source = _rule_set_detail(db, request.source_rule_set_id)
                for key in ("description", "degree_level", "manual_checklist"):
                    if key not in request.model_fields_set:
                        fields[key] = getattr(source, key)
                items = [item.model_dump(exclude={"id", "rule_set_id"}) for item in source.rule_items]
            else:
                items = [item.model_dump() for item in request.rule_items]

            rule_set = RuleSet(**fields, is_default=False)
            db.add(rule_set)
            db.flush()
            db.add_all(RuleItem(rule_set_id=rule_set.id, **item) for item in items)
            return _rule_set_detail(db, rule_set.id)
    except IntegrityError as exc:
        # Concurrent creates can race on the template code and version.
        raise HTTPException(status_code=409, detail="规则模板编号和版本已存在") from exc


@router.patch("/rule-items/{rule_item_id}")
def update_rule_item(
    rule_item_id: UUID, request: RuleItemUpdate, db: Annotated[Session, Depends(get_db)]
) -> RuleItemResponse:
    with db.begin():
        item = db.get(RuleItem, rule_item_id, with_for_update=True)
        if item is None:
            raise HTTPException(status_code=404, detail="规则项不存在")
        changes = request.model_dump(exclude_unset=True)
        if "params" in changes:
            changes["params"] = item.params | changes["params"]
            try:
                validate_rule_params(item.rule_code, changes["params"])
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        for key, value in changes.items():
            setattr(item, key, value)
        if changes:
            rule_set = db.get(RuleSet, item.rule_set_id)
            rule_set.updated_at = datetime.now(timezone.utc)
        return RuleItemResponse.model_validate(item)
