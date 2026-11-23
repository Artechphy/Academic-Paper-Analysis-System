"""Persist thesis revision sessions and feedback."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0002_revision_sessions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "revision_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("check_run_id", sa.Uuid(), sa.ForeignKey("check_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_set_id", sa.Uuid(), sa.ForeignKey("rule_sets.id"), nullable=False),
        sa.Column("target_file_name", sa.String(255), nullable=False),
        sa.Column("working_docx_path", sa.Text()),
        sa.Column("annotated_pdf_path", sa.Text()),
        sa.Column("annotated_page_mode", sa.String(16)),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("comparison_ready", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("llm_used", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("llm_model", sa.String(64)),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), server_default=sa.text("100.00"), nullable=False),
        *(sa.Column(name, sa.Integer(), server_default=sa.text("0"), nullable=False)
          for name in ("error_count", "warning_count", "original_error_count")),
        sa.Column("current_ir", JSONB(), nullable=False),
        *(sa.Column(name, JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False)
          for name in ("current_violations", "rulebook", "changes", "modified_paragraphs")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("verdict IN ('pass', 'fail', 'error')", name="ck_revision_sessions_verdict"),
        sa.CheckConstraint("annotated_page_mode IN ('issues_only', 'full')", name="ck_revision_sessions_page_mode"),
    )
    op.create_index("ix_revision_sessions_run_updated", "revision_sessions", ["check_run_id", sa.text("updated_at DESC")])
    op.create_table(
        "revision_feedbacks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("revision_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(16), nullable=False),
        sa.Column("rule_code", sa.String(64)),
        sa.Column("paragraph_index", sa.Integer()),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("author IN ('user', 'agent')", name="ck_revision_feedbacks_author"),
    )
    op.create_index("ix_revision_feedbacks_session_created", "revision_feedbacks", ["session_id", "created_at"])


def downgrade():
    op.drop_table("revision_feedbacks")
    op.drop_table("revision_sessions")
