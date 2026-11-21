"""Create the paper analysis tables, batch counter trigger and analysis views."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_sets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), server_default="1.0.0", nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("degree_level", sa.String(32), server_default="master", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("manual_checklist", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("code", "version", name="uq_rule_sets_code_version"),
        sa.CheckConstraint("degree_level IN ('master', 'doctor', 'general')", name="ck_rule_sets_degree_level"),
    )
    op.create_index(
        "uq_rule_sets_default", "rule_sets", ["is_default"], unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
    )

    op.create_table(
        "rule_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("rule_set_id", sa.Uuid(), sa.ForeignKey("rule_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_code", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("applies_to", sa.String(16), nullable=False),
        sa.Column("params", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.UniqueConstraint("rule_set_id", "rule_code", name="uq_rule_items_rule_set_code"),
        sa.CheckConstraint(
            "category IN ('file', 'page', 'header_footer', 'structure', 'cover', "
            "'typography', 'abstract', 'figure_table', 'reference')",
            name="ck_rule_items_category",
        ),
        sa.CheckConstraint("severity IN ('error', 'warning')", name="ck_rule_items_severity"),
        sa.CheckConstraint("applies_to IN ('docx', 'pdf', 'both')", name="ck_rule_items_applies_to"),
    )
    op.create_index("ix_rule_items_params", "rule_items", ["params"], postgresql_using="gin")
    op.create_index("ix_rule_items_rule_set_category", "rule_items", ["rule_set_id", "category"])

    op.create_table(
        "papers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_ext", sa.String(16), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column("detected_title", sa.String(512)),
        sa.Column("parse_status", sa.String(16), nullable=False),
        sa.Column("parse_error", sa.Text()),
        sa.Column("parsed_ir", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("file_ext IN ('docx', 'pdf')", name="ck_papers_file_ext"),
        sa.CheckConstraint("parse_status IN ('success', 'failed')", name="ck_papers_parse_status"),
    )
    op.create_index("ix_papers_sha256", "papers", ["sha256"])
    op.create_index("ix_papers_parsed_ir", "papers", ["parsed_ir"], postgresql_using="gin")

    op.create_table(
        "check_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("rule_set_id", sa.Uuid(), sa.ForeignKey("rule_sets.id"), nullable=False),
        sa.Column("total_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("pass_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("fail_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="ck_check_batches_status"),
    )

    op.create_table(
        "check_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("check_batches.id", ondelete="SET NULL")),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_set_id", sa.Uuid(), sa.ForeignKey("rule_sets.id"), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), server_default=sa.text("100.00"), nullable=False),
        sa.Column("error_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("warning_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("passed_rules_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("skipped_rules_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("verdict IN ('pass', 'fail', 'error')", name="ck_check_runs_verdict"),
    )
    op.create_index("ix_check_runs_batch_verdict", "check_runs", ["batch_id", "verdict"])
    op.create_index("ix_check_runs_paper_checked_at", "check_runs", ["paper_id", sa.text("checked_at DESC")])
    op.create_index("ix_check_runs_rule_set_verdict", "check_runs", ["rule_set_id", "verdict"])

    op.create_table(
        "check_violations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("check_run_id", sa.Uuid(), sa.ForeignKey("check_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_item_id", sa.Uuid(), sa.ForeignKey("rule_items.id", ondelete="SET NULL")),
        sa.Column("rule_code", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("rule_name", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("location", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("actual", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.CheckConstraint("severity IN ('error', 'warning')", name="ck_check_violations_severity"),
    )
    op.create_index("ix_check_violations_run_severity", "check_violations", ["check_run_id", "severity"])
    op.create_index("ix_check_violations_rule_code", "check_violations", ["rule_code"])
    op.create_index("ix_check_violations_location", "check_violations", ["location"], postgresql_using="gin")

    op.execute("""
        CREATE FUNCTION sync_check_batch_counts() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            affected_batch_ids uuid[];
        BEGIN
            IF TG_OP = 'INSERT' THEN
                affected_batch_ids := ARRAY[NEW.batch_id];
            ELSIF TG_OP = 'DELETE' THEN
                affected_batch_ids := ARRAY[OLD.batch_id];
            ELSE
                affected_batch_ids := ARRAY[OLD.batch_id, NEW.batch_id];
            END IF;

            -- Lock before aggregating so a concurrent writer cannot overwrite fresh counts.
            -- NO KEY UPDATE is compatible with the locks used by foreign key checks.
            PERFORM id
            FROM check_batches
            WHERE id = ANY(affected_batch_ids)
            ORDER BY id
            FOR NO KEY UPDATE;

            UPDATE check_batches AS batch
            SET total_count = counts.total_count,
                pass_count = counts.pass_count,
                fail_count = counts.fail_count,
                error_count = counts.error_count
            FROM (
                SELECT affected.id,
                       COUNT(run.batch_id) AS total_count,
                       COUNT(*) FILTER (WHERE run.verdict = 'pass') AS pass_count,
                       COUNT(*) FILTER (WHERE run.verdict = 'fail') AS fail_count,
                       COUNT(*) FILTER (WHERE run.verdict = 'error') AS error_count
                FROM check_batches AS affected
                LEFT JOIN check_runs AS run ON run.batch_id = affected.id
                WHERE affected.id = ANY(affected_batch_ids)
                GROUP BY affected.id
            ) AS counts
            WHERE batch.id = counts.id;

            RETURN NULL;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_sync_check_batch_counts
        AFTER INSERT OR UPDATE OR DELETE ON check_runs
        FOR EACH ROW EXECUTE FUNCTION sync_check_batch_counts()
    """)
    op.execute("""
        CREATE VIEW v_rule_violation_stats AS
        SELECT violation.rule_code,
               MIN(violation.rule_name) AS rule_name,
               MIN(violation.category) AS category,
               COUNT(*) AS violation_count,
               COUNT(DISTINCT run.paper_id) AS affected_paper_count,
               COUNT(*)::numeric / SUM(COUNT(*)) OVER () AS violation_ratio,
               DENSE_RANK() OVER (ORDER BY COUNT(*) DESC) AS violation_rank
        FROM check_violations AS violation
        LEFT JOIN check_runs AS run ON run.id = violation.check_run_id
        GROUP BY violation.rule_code
    """)
    op.execute("""
        CREATE VIEW v_batch_summary AS
        SELECT batch.id AS batch_id,
               batch.name,
               batch.rule_set_id,
               batch.status,
               batch.created_at,
               batch.completed_at,
               batch.total_count,
               batch.pass_count,
               batch.fail_count,
               batch.error_count,
               COALESCE(batch.pass_count::numeric / NULLIF(batch.total_count, 0), 0) AS pass_rate,
               ROUND(AVG(run.score), 2) AS avg_score,
               ROUND(AVG(run.duration_ms), 2) AS avg_duration_ms
        FROM check_batches AS batch
        LEFT JOIN check_runs AS run ON run.batch_id = batch.id
        GROUP BY batch.id
    """)


def downgrade() -> None:
    op.execute("DROP VIEW v_batch_summary")
    op.execute("DROP VIEW v_rule_violation_stats")
    op.execute("DROP TRIGGER trg_sync_check_batch_counts ON check_runs")
    op.execute("DROP FUNCTION sync_check_batch_counts()")
    op.drop_table("check_violations")
    op.drop_table("check_runs")
    op.drop_table("check_batches")
    op.drop_table("papers")
    op.drop_table("rule_items")
    op.drop_table("rule_sets")
