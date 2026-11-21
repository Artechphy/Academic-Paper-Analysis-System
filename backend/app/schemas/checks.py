"""API models for batch checks, individual runs and statistics."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.engine.evaluator import Violation
from app.schemas.ir import DetectedSectionIR, DocumentStatsIR

Verdict = Literal["pass", "fail", "error"]


class RecheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_set_id: UUID


class CheckRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    batch_id: UUID | None
    paper_id: UUID
    rule_set_id: UUID
    file_name: str
    file_ext: Literal["docx", "pdf"]
    file_size: int
    page_count: int | None
    detected_title: str | None
    parse_status: Literal["success", "failed"]
    parse_error: str | None
    verdict: Verdict
    score: float
    error_count: int
    warning_count: int
    passed_rules_count: int
    skipped_rules_count: int
    duration_ms: int
    checked_at: datetime


class IRSummary(BaseModel):
    page_count: int
    stats: DocumentStatsIR
    sections: list[DetectedSectionIR]
    capabilities: dict[str, bool]
    is_image_only_pdf: bool


class ViolationResponse(Violation):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


class CheckRunDetail(CheckRunSummary):
    ir_summary: IRSummary | None
    violations: list[ViolationResponse]
    manual_checklist: list[str]


class BatchSummary(BaseModel):
    id: UUID
    name: str
    rule_set_id: UUID
    status: Literal["pending", "running", "completed", "failed"]
    created_at: datetime
    completed_at: datetime | None
    total_count: int
    pass_count: int
    fail_count: int
    error_count: int
    pass_rate: float
    avg_score: float | None
    avg_duration_ms: float | None


class BatchDetail(BatchSummary):
    results: list[CheckRunSummary]


class RuleViolationStats(BaseModel):
    rule_code: str
    rule_name: str
    category: str
    violation_count: int
    affected_paper_count: int
    violation_ratio: float
    violation_rank: int


class StatsOverview(BaseModel):
    total_count: int
    pass_count: int
    fail_count: int
    error_count: int
    pass_rate: float
    top_violations: list[RuleViolationStats]
