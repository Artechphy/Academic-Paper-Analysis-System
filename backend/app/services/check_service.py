"""Run checks, persist their results and query the database analysis views."""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import BinaryIO
from uuid import UUID

from sqlalchemy import Uuid, case, column, func, select, table, text
from sqlalchemy.orm import Session

from app.db.models import CheckBatch, CheckRun, CheckViolation, Paper, RuleItem, RuleSet
from app.engine.evaluator import evaluate
from app.schemas.checks import (
    BatchDetail,
    BatchSummary,
    CheckRunDetail,
    CheckRunSummary,
    IRSummary,
    StatsOverview,
    Verdict,
)
from app.schemas.ir import DocumentIR
from app.services.paper_service import prepare_paper

_BATCH_SUMMARY = table(
    "v_batch_summary",
    column("batch_id", Uuid),
    column("name"),
    column("rule_set_id", Uuid),
    column("status"),
    column("created_at"),
    column("completed_at"),
    column("total_count"),
    column("pass_count"),
    column("fail_count"),
    column("error_count"),
    column("pass_rate"),
    column("avg_score"),
    column("avg_duration_ms"),
)

_PAPER_FIELDS = (
    Paper.file_name,
    Paper.file_ext,
    Paper.file_size,
    Paper.page_count,
    Paper.detected_title,
    Paper.parse_status,
    Paper.parse_error,
)


def rule_items_query(rule_set_id: UUID):
    return (
        select(RuleItem)
        .where(RuleItem.rule_set_id == rule_set_id)
        .order_by(RuleItem.sort_order, RuleItem.rule_code)
    )


def _record_run(
    db: Session, paper: Paper, rule_set_id: UUID, rules: Sequence[RuleItem],
    batch_id: UUID | None = None,
) -> CheckRun:
    result = evaluate(paper.parsed_ir, rules, parse_status=paper.parse_status)
    run = CheckRun(
        batch_id=batch_id,
        paper_id=paper.id,
        rule_set_id=rule_set_id,
        **result.model_dump(exclude={"violations"}),
    )
    db.add(run)
    db.flush()
    db.add_all(
        CheckViolation(check_run_id=run.id, **violation.model_dump())
        for violation in result.violations
    )
    return run


def _batch_summary_query():
    return select(_BATCH_SUMMARY.c.batch_id.label("id"), *_BATCH_SUMMARY.c[1:])


def list_batches(db: Session) -> list[BatchSummary]:
    rows = db.execute(
        _batch_summary_query().order_by(_BATCH_SUMMARY.c.created_at.desc(), _BATCH_SUMMARY.c.batch_id)
    ).mappings()
    return [BatchSummary.model_validate(row) for row in rows]


def _batch_summary(db: Session, batch_id: UUID) -> BatchSummary | None:
    row = db.execute(
        _batch_summary_query().where(_BATCH_SUMMARY.c.batch_id == batch_id)
    ).mappings().one_or_none()
    return BatchSummary.model_validate(row) if row is not None else None


def _run_summary_query():
    return select(CheckRun.__table__, *_PAPER_FIELDS).join(Paper, Paper.id == CheckRun.paper_id)


def create_batch(
    db: Session, rule_set_id: UUID, name: str, files: Sequence[tuple[str, BinaryIO]]
) -> BatchDetail:
    rules = db.scalars(rule_items_query(rule_set_id)).all()
    batch = CheckBatch(name=name, rule_set_id=rule_set_id, status="running")
    db.add(batch)
    db.flush()

    run_ids = []
    for filename, stream in files:
        paper = prepare_paper(stream.read(), filename)
        db.add(paper)
        db.flush()
        run = _record_run(db, paper, rule_set_id, rules, batch.id)
        run_ids.append(run.id)

    batch.status = "completed"
    batch.completed_at = datetime.now(timezone.utc)
    db.flush()
    summary = _batch_summary(db, batch.id)
    assert summary is not None
    rows = db.execute(_run_summary_query().where(CheckRun.batch_id == batch.id)).mappings()
    results = {row["id"]: CheckRunSummary.model_validate(row) for row in rows}
    return BatchDetail(**summary.model_dump(), results=[results[run_id] for run_id in run_ids])


def get_batch(
    db: Session, batch_id: UUID, verdict: Verdict | None, q: str | None
) -> BatchDetail | None:
    summary = _batch_summary(db, batch_id)
    if summary is None:
        return None
    query = _run_summary_query().where(CheckRun.batch_id == batch_id)
    if verdict is not None:
        query = query.where(CheckRun.verdict == verdict)
    if q:
        query = query.where(Paper.file_name.icontains(q, autoescape=True))
    rows = db.execute(
        query.order_by(CheckRun.checked_at, Paper.file_name, CheckRun.id)
    ).mappings()
    return BatchDetail(
        **summary.model_dump(),
        results=[CheckRunSummary.model_validate(row) for row in rows],
    )


def _ir_summary(snapshot: dict | None) -> IRSummary | None:
    if snapshot is None:
        return None
    document = DocumentIR.model_validate(snapshot)
    return IRSummary.model_validate(
        document.model_dump(
            include={"page_count", "stats", "sections", "capabilities", "is_image_only_pdf"}
        )
    )


def get_run(db: Session, run_id: UUID) -> CheckRunDetail | None:
    row = db.execute(
        _run_summary_query()
        .add_columns(Paper.parsed_ir, RuleSet.manual_checklist)
        .join(RuleSet, RuleSet.id == CheckRun.rule_set_id)
        .where(CheckRun.id == run_id)
    ).mappings().one_or_none()
    if row is None:
        return None
    violations = db.scalars(
        select(CheckViolation)
        .where(CheckViolation.check_run_id == run_id)
        .order_by(
            case((CheckViolation.severity == "error", 0), else_=1),
            CheckViolation.rule_code,
            CheckViolation.id,
        )
    ).all()
    data = dict(row)
    snapshot = data.pop("parsed_ir")
    return CheckRunDetail(**data, ir_summary=_ir_summary(snapshot), violations=violations)


def recheck(db: Session, paper: Paper, rule_set_id: UUID) -> CheckRunDetail:
    rules = db.scalars(rule_items_query(rule_set_id)).all()
    run = _record_run(db, paper, rule_set_id, rules)
    db.flush()
    detail = get_run(db, run.id)
    assert detail is not None
    return detail


def get_overview(db: Session) -> StatsOverview:
    # Batch counters include their attached runs. Add independent rechecks once.
    counts = db.execute(text("""
        SELECT COALESCE(SUM(total_count), 0) AS total_count,
               COALESCE(SUM(pass_count), 0) AS pass_count,
               COALESCE(SUM(fail_count), 0) AS fail_count,
               COALESCE(SUM(error_count), 0) AS error_count
        FROM (
            SELECT total_count, pass_count, fail_count, error_count FROM v_batch_summary
            UNION ALL
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE verdict = 'pass'),
                   COUNT(*) FILTER (WHERE verdict = 'fail'),
                   COUNT(*) FILTER (WHERE verdict = 'error')
            FROM check_runs
            WHERE batch_id IS NULL
        ) AS counts
        """)).mappings().one()
    top_violations = db.execute(text("""
        SELECT rule_code, rule_name, category, violation_count, affected_paper_count,
               violation_ratio, violation_rank
        FROM v_rule_violation_stats
        ORDER BY violation_rank, rule_code
        LIMIT 10
        """)).mappings().all()
    total = counts["total_count"]
    return StatsOverview(
        **counts,
        pass_rate=counts["pass_count"] / total if total else 0,
        top_violations=top_violations,
    )
