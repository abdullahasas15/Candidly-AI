"""Add provider routing, latency tracking, and session runtime_state columns.

Revision ID: 20261014_provider_routing_and_runtime_state
Revises: 20261013_role_templates_and_blueprint_quality
"""

from alembic import op
import sqlalchemy as sa


revision = "20261014_provider_routing_and_runtime_state"
down_revision = "20261013_role_templates_and_blueprint_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    bp_cols = {c["name"] for c in inspector.get_columns("interview_blueprints")}
    if "generation_provider" not in bp_cols:
        op.add_column("interview_blueprints", sa.Column("generation_provider", sa.String(50), nullable=True))
    if "generation_model" not in bp_cols:
        op.add_column("interview_blueprints", sa.Column("generation_model", sa.String(100), nullable=True))
    if "generation_latency_ms" not in bp_cols:
        op.add_column("interview_blueprints", sa.Column("generation_latency_ms", sa.Float(), nullable=True))
    if "generation_stages_ms" not in bp_cols:
        op.add_column("interview_blueprints", sa.Column("generation_stages_ms", sa.JSON(), nullable=True))
    if "is_generated_with_backup" not in bp_cols:
        op.add_column("interview_blueprints", sa.Column("is_generated_with_backup", sa.Boolean(), server_default=sa.text("false"), nullable=False))

    sess_cols = {c["name"] for c in inspector.get_columns("interview_sessions")}
    if "runtime_state" not in sess_cols:
        op.add_column("interview_sessions", sa.Column("runtime_state", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=True))

    turn_cols = {c["name"] for c in inspector.get_columns("interview_transcript_turns")}
    if "provider" not in turn_cols:
        op.add_column("interview_transcript_turns", sa.Column("provider", sa.String(50), nullable=True))
    if "model_name" not in turn_cols:
        op.add_column("interview_transcript_turns", sa.Column("model_name", sa.String(100), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    bp_cols = {c["name"] for c in inspector.get_columns("interview_blueprints")}
    if "is_generated_with_backup" in bp_cols:
        op.drop_column("interview_blueprints", "is_generated_with_backup")
    if "generation_stages_ms" in bp_cols:
        op.drop_column("interview_blueprints", "generation_stages_ms")
    if "generation_latency_ms" in bp_cols:
        op.drop_column("interview_blueprints", "generation_latency_ms")
    if "generation_model" in bp_cols:
        op.drop_column("interview_blueprints", "generation_model")
    if "generation_provider" in bp_cols:
        op.drop_column("interview_blueprints", "generation_provider")

    sess_cols = {c["name"] for c in inspector.get_columns("interview_sessions")}
    if "runtime_state" in sess_cols:
        op.drop_column("interview_sessions", "runtime_state")

    turn_cols = {c["name"] for c in inspector.get_columns("interview_transcript_turns")}
    if "model_name" in turn_cols:
        op.drop_column("interview_transcript_turns", "model_name")
    if "provider" in turn_cols:
        op.drop_column("interview_transcript_turns", "provider")
