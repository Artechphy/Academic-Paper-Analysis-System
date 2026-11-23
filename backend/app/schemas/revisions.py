"""Requests and responses for the thesis revision workspace."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from app.schemas.checks import Verdict, ViolationResponse
from app.schemas.ir import Alignment, ParagraphIR

PageMode = Literal["issues_only", "full"]
DiffSource = Literal["manual", "rule", "llm"]


class AnchorLocation(BaseModel):
    page: int | None = None
    paragraph_index: int | None = None
    bbox: Annotated[list[FiniteFloat], Field(min_length=4, max_length=4)] | None = None
    excerpt: str | None = None


class RulebookEntry(BaseModel):
    rule_code: str
    rule_name: str
    category: str
    severity: Literal["error", "warning"]
    scope: Literal["global", "cluster", "point"]
    status: Literal["open", "fixed", "ignored"]
    total_count: int
    original_count: int
    expected: str
    actual_summary: str
    guidance: str
    bubble_note: str
    can_auto_fix: bool
    affected_paragraphs: list[int]
    affected_pages: list[int]
    representative_anchors: list[AnchorLocation]


class ParagraphDiff(BaseModel):
    paragraph_index: int
    page_no: int | None = None
    section_key: str | None = None
    before_text: str
    after_text: str
    style_changes: list[str]
    source: DiffSource
    summary: str


class RevisionFeedbackItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    author: Literal["user", "agent"]
    rule_code: str | None
    paragraph_index: int | None
    instruction: str
    summary: str | None
    created_at: datetime


class RevisionSessionDetail(BaseModel):
    id: UUID
    check_run_id: UUID
    paper_id: UUID
    rule_set_id: UUID
    file_name: str
    target_file_name: str
    file_ext: Literal["docx", "pdf"]
    editable: bool
    version: int
    comparison_ready: bool
    annotated_pdf_ready: bool
    annotated_page_mode: PageMode | None
    llm_used: bool
    llm_model: str | None
    verdict: Verdict
    score: float
    error_count: int
    warning_count: int
    original_error_count: int
    rulebook: list[RulebookEntry]
    original_paragraphs: list[ParagraphIR]
    current_paragraphs: list[ParagraphIR]
    violations: list[ViolationResponse]
    changes: list[ParagraphDiff]
    modified_paragraphs: list[int]
    feedbacks: list[RevisionFeedbackItem]
    updated_at: datetime


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParagraphEditRequest(RevisionRequest):
    text: str | None = Field(default=None, max_length=50000)
    font_name: str | None = Field(default=None, min_length=1, max_length=128)
    font_size_pt: float | None = Field(default=None, ge=1, le=1638, allow_inf_nan=False)
    bold: bool | None = None
    alignment: Alignment | None = None
    line_spacing_pt: float | None = Field(default=None, ge=.05, le=1584, allow_inf_nan=False)
    revert: bool = False


class ParagraphEditResponse(BaseModel):
    paragraph: ParagraphIR
    paragraph_violations: list[ViolationResponse]
    resolved_count: int
    remaining_count: int
    verdict: Verdict
    score: float
    error_count: int
    warning_count: int
    rulebook: list[RulebookEntry]
    changes: list[ParagraphDiff]
    modified_paragraphs: list[int]
    version: int


class DocumentSettingsRequest(RevisionRequest):
    target_file_name: str | None = Field(default=None, max_length=255)
    fix_page_size_a4: bool = False
    fix_margins: bool = False
    fix_headers: bool = False


class AutoFixRequest(RevisionRequest):
    instruction: str | None = Field(default=None, max_length=4000)
    rule_codes: list[str] | None = Field(default=None, max_length=50)


class AnnotatedPdfExportRequest(RevisionRequest):
    page_mode: PageMode = "issues_only"


class AnnotatedPdfExportResponse(BaseModel):
    annotated_pdf_ready: bool
    page_mode: PageMode
    page_count: int
    download_url: str
