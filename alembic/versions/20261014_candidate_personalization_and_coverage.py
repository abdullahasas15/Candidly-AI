"""Add status and input_hash to candidate_personalizations, and evidence_quote to session_expectation_coverage.

Revision ID: 20261014_candidate_personalization_and_coverage
Revises: 20261014_provider_routing_and_runtime_state
"""

from alembic import op
import sqlalchemy as sa


revision = "20261014_candidate_personalization_and_coverage"
down_revision = "20261014_provider_routing_and_runtime_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    cp_cols = {c["name"] for c in inspector.get_columns("candidate_personalizations")}
    if "status" not in cp_cols:
        op.add_column("candidate_personalizations", sa.Column("status", sa.String(20), server_default="completed", nullable=False))
    if "input_hash" not in cp_cols:
        op.add_column("candidate_personalizations", sa.Column("input_hash", sa.String(64), nullable=True))
        op.create_index("ix_candidate_personalizations_input_hash", "candidate_personalizations", ["input_hash"])

    sec_cols = {c["name"] for c in inspector.get_columns("session_expectation_coverage")}
    if "evidence_quote" not in sec_cols:
        op.add_column("session_expectation_coverage", sa.Column("evidence_quote", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    sec_cols = {c["name"] for c in inspector.get_columns("session_expectation_coverage")}
    if "evidence_quote" in sec_cols:
        op.drop_column("session_expectation_coverage", "evidence_quote")

    cp_cols = {c["name"] for c in inspector.get_columns("candidate_personalizations")}
    if "input_hash" in cp_cols:
        op.drop_index("ix_candidate_personalizations_input_hash", table_name="candidate_personalizations")
        op.drop_column("candidate_personalizations", "input_hash")
    if "status" in cp_cols:
        op.drop_column("candidate_personalizations", "status")
