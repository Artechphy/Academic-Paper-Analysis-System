from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuleSet(Base):
    __tablename__ = "rule_sets"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_rule_sets_code_version"),
        CheckConstraint(
            "degree_level IN ('master', 'doctor', 'general')",
            name="ck_rule_sets_degree_level",
        ),
        Index(
            "uq_rule_sets_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default IS TRUE"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32), server_default="1.0.0")
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    degree_level: Mapped[str] = mapped_column(String(32), server_default="master")
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=false())
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    manual_checklist: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuleItem(Base):
    __tablename__ = "rule_items"
    __table_args__ = (
        UniqueConstraint("rule_set_id", "rule_code", name="uq_rule_items_rule_set_code"),
        CheckConstraint(
            "category IN ('file', 'page', 'header_footer', 'structure', 'cover', "
            "'typography', 'abstract', 'figure_table', 'reference')",
            name="ck_rule_items_category",
        ),
        CheckConstraint("severity IN ('error', 'warning')", name="ck_rule_items_severity"),
        CheckConstraint("applies_to IN ('docx', 'pdf', 'both')", name="ck_rule_items_applies_to"),
        Index("ix_rule_items_params", "params", postgresql_using="gin"),
        Index("ix_rule_items_rule_set_category", "rule_set_id", "category"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    rule_set_id: Mapped[UUID] = mapped_column(ForeignKey("rule_sets.id", ondelete="CASCADE"))
    rule_code: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    applies_to: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        CheckConstraint("file_ext IN ('docx', 'pdf')", name="ck_papers_file_ext"),
        CheckConstraint("parse_status IN ('success', 'failed')", name="ck_papers_parse_status"),
        Index("ix_papers_sha256", "sha256"),
        Index("ix_papers_parsed_ir", "parsed_ir", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    file_name: Mapped[str] = mapped_column(String(255))
    file_ext: Mapped[str] = mapped_column(String(16))
    file_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(CHAR(64))
    storage_path: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    detected_title: Mapped[str | None] = mapped_column(String(512))
    parse_status: Mapped[str] = mapped_column(String(16))
    parse_error: Mapped[str | None] = mapped_column(Text)
    parsed_ir: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CheckBatch(Base):
    __tablename__ = "check_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_check_batches_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128))
    rule_set_id: Mapped[UUID] = mapped_column(ForeignKey("rule_sets.id"))
    total_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    pass_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    fail_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CheckRun(Base):
    __tablename__ = "check_runs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("check_batches.id", ondelete="SET NULL"))
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    rule_set_id: Mapped[UUID] = mapped_column(ForeignKey("rule_sets.id"))
    verdict: Mapped[str] = mapped_column(String(16))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("100.00"))
    error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    warning_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    passed_rules_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    skipped_rules_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    duration_ms: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("verdict IN ('pass', 'fail', 'error')", name="ck_check_runs_verdict"),
        Index("ix_check_runs_batch_verdict", batch_id, verdict),
        Index("ix_check_runs_paper_checked_at", paper_id, checked_at.desc()),
        Index("ix_check_runs_rule_set_verdict", rule_set_id, verdict),
    )


class CheckViolation(Base):
    __tablename__ = "check_violations"
    __table_args__ = (
        CheckConstraint("severity IN ('error', 'warning')", name="ck_check_violations_severity"),
        Index("ix_check_violations_run_severity", "check_run_id", "severity"),
        Index("ix_check_violations_rule_code", "rule_code"),
        Index("ix_check_violations_location", "location", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    check_run_id: Mapped[UUID] = mapped_column(ForeignKey("check_runs.id", ondelete="CASCADE"))
    rule_item_id: Mapped[UUID | None] = mapped_column(ForeignKey("rule_items.id", ondelete="SET NULL"))
    rule_code: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))
    rule_name: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16))
    location: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    expected: Mapped[str] = mapped_column(Text)
    actual: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)


class RevisionSession(Base):
    __tablename__ = "revision_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    check_run_id: Mapped[UUID] = mapped_column(ForeignKey("check_runs.id", ondelete="CASCADE"))
    paper_id: Mapped[UUID] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"))
    rule_set_id: Mapped[UUID] = mapped_column(ForeignKey("rule_sets.id"))
    target_file_name: Mapped[str] = mapped_column(String(255))
    working_docx_path: Mapped[str | None] = mapped_column(Text)
    annotated_pdf_path: Mapped[str | None] = mapped_column(Text)
    annotated_page_mode: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    comparison_ready: Mapped[bool] = mapped_column(Boolean, server_default=false())
    llm_used: Mapped[bool] = mapped_column(Boolean, server_default=false())
    llm_model: Mapped[str | None] = mapped_column(String(64))
    verdict: Mapped[str] = mapped_column(String(16))
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("100.00"))
    error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    warning_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    original_error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    current_ir: Mapped[dict[str, Any]] = mapped_column(JSONB)
    current_violations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    rulebook: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    modified_paragraphs: Mapped[list[int]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("verdict IN ('pass', 'fail', 'error')", name="ck_revision_sessions_verdict"),
        CheckConstraint("annotated_page_mode IN ('issues_only', 'full')", name="ck_revision_sessions_page_mode"),
        Index("ix_revision_sessions_run_updated", check_run_id, updated_at.desc()),
    )


class RevisionFeedback(Base):
    __tablename__ = "revision_feedbacks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("revision_sessions.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    author: Mapped[str] = mapped_column(String(16))
    rule_code: Mapped[str | None] = mapped_column(String(64))
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    instruction: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("author IN ('user', 'agent')", name="ck_revision_feedbacks_author"),
        Index("ix_revision_feedbacks_session_created", session_id, created_at),
    )
