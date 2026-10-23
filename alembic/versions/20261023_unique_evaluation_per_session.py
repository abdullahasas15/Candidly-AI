"""Enforce exactly one evaluation per interview session.

Deduplicates legacy rows (keeps the earliest per session_id) and adds a unique
index on interview_evaluations.session_id, matching the model-level unique=True.

Revision ID: 20261023_unique_evaluation_per_session
Revises: 20261022_ws_ticket_single_use
"""

from alembic import op
import sqlalchemy as sa


revision = "20261023_unique_evaluation_per_session"
down_revision = "20261022_ws_ticket_single_use"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "interview_evaluations" not in inspector.get_table_names():
        return

    existing_indexes = {ix["name"] for ix in inspector.get_indexes("interview_evaluations")}
    if "uq_interview_evaluations_session_id" in existing_indexes:
        return

    # Keep the earliest evaluation per session (tie-break on id) before enforcing uniqueness.
    bind.execute(
        sa.text(
            "DELETE FROM interview_evaluations a USING interview_evaluations b "
            "WHERE a.session_id = b.session_id "
            "AND (a.created_at > b.created_at OR (a.created_at = b.created_at AND a.id > b.id))"
        )
    )
    op.create_index(
        "uq_interview_evaluations_session_id",
        "interview_evaluations",
        ["session_id"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "interview_evaluations" not in inspector.get_table_names():
        return
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("interview_evaluations")}
    if "uq_interview_evaluations_session_id" in existing_indexes:
        op.drop_index("uq_interview_evaluations_session_id", table_name="interview_evaluations")
