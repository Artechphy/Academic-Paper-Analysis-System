"""Treat built-in spacing and margin findings as warnings."""

from alembic import op
import sqlalchemy as sa

revision = "0003_spacing_rule_severity"
down_revision = "0002_revision_sessions"
branch_labels = None
depends_on = None


_rules = sa.table("rule_items", sa.column("id", sa.Uuid()), sa.column("rule_set_id", sa.Uuid()),
                  sa.column("rule_code", sa.String()), sa.column("severity", sa.String()))
_templates = sa.table("rule_sets", sa.column("id", sa.Uuid()), sa.column("code", sa.String()),
                      sa.column("version", sa.String()))
_changes = sa.table("spacing_rule_severity_0003", sa.column("rule_item_id", sa.Uuid()))


def _built_in_spacing():
    return sa.and_(
        _rules.c.rule_set_id.in_(sa.select(_templates.c.id).where(
            _templates.c.code.in_(("fjnu_master_2019", "fjnu_doctor_2019", "general_academic_v1")),
            _templates.c.version == "1.0.0",
        )),
        _rules.c.rule_code.in_(("LINE_SPACING_MIN", "PAGE_MARGINS")),
    )


def upgrade():
    # Remember exactly which rows changed so downgrade preserves pre-existing warnings.
    op.create_table(
        _changes.name,
        sa.Column("rule_item_id", sa.Uuid(), sa.ForeignKey("rule_items.id", ondelete="CASCADE"), primary_key=True),
    )
    op.execute(_changes.insert().from_select(
        ["rule_item_id"], sa.select(_rules.c.id).where(_built_in_spacing(), _rules.c.severity == "error"),
    ))
    op.execute(_rules.update().where(_rules.c.id.in_(sa.select(_changes.c.rule_item_id))).values(severity="warning"))


def downgrade():
    op.execute(_rules.update().where(
        _built_in_spacing(), _rules.c.severity == "warning", _rules.c.id.in_(sa.select(_changes.c.rule_item_id)),
    ).values(severity="error"))
    op.drop_table(_changes.name)
