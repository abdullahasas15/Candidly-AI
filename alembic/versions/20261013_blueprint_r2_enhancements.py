"""Add input_hash and is_stale to interview_blueprints, and source to blueprint_questions.

Revision ID: 20261013_blueprint_r2_enhancements
Revises: 20261013_job_interview_blueprints
"""

from alembic import op
import sqlalchemy as sa


revision = "20261013_blueprint_r2_enhancements"
down_revision = "20261013_job_interview_blueprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. Add input_hash and is_stale to interview_blueprints
    if "interview_blueprints" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_blueprints")}
        if "input_hash" not in cols:
            op.add_column(
                "interview_blueprints",
                sa.Column("input_hash", sa.String(64), nullable=True),
            )
        if "is_stale" not in cols:
            op.add_column(
                "interview_blueprints",
                sa.Column("is_stale", sa.Boolean(), server_default="false", nullable=False),
            )

    # 2. Add source to blueprint_questions
    if "blueprint_questions" in tables:
        cols = {c["name"] for c in inspector.get_columns("blueprint_questions")}
        if "source" not in cols:
            op.add_column(
                "blueprint_questions",
                sa.Column("source", sa.String(20), server_default="llm", nullable=False),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "blueprint_questions" in tables:
        cols = {c["name"] for c in inspector.get_columns("blueprint_questions")}
        if "source" in cols:
            op.drop_column("blueprint_questions", "source")

    if "interview_blueprints" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_blueprints")}
        if "is_stale" in cols:
            op.drop_column("interview_blueprints", "is_stale")
        if "input_hash" in cols:
            op.drop_column("interview_blueprints", "input_hash")
