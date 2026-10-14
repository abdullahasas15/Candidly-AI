"""Add auditable question generation and transcript runtime tables.

Revision ID: 20261005_interview_generation_runtime
Revises:
"""

from alembic import op
import sqlalchemy as sa


revision = "20261005_interview_generation_runtime"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "interview_generation_runs" not in tables:
        op.create_table(
            "interview_generation_runs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("application_id", sa.String(36), sa.ForeignKey("job_applications.id", ondelete="CASCADE"), nullable=False),
            sa.Column("job_id", sa.String(36), sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("model_name", sa.String(100), nullable=False),
            sa.Column("prompt_template_version", sa.String(50), nullable=False),
            sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
            sa.Column("resume_version_used", sa.String(64)),
            sa.Column("job_rubric_version_used", sa.String(64)),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failure_reason", sa.Text()),
            sa.Column("gemini_request_id", sa.String(255)),
            sa.Column("token_usage_json", sa.JSON()),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("completed_at", sa.DateTime()),
        )
        op.create_index("ix_interview_generation_runs_application_id", "interview_generation_runs", ["application_id"])
        op.create_index("ix_interview_generation_runs_input_snapshot_hash", "interview_generation_runs", ["input_snapshot_hash"])

    if "interview_questions" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_questions")}
        if "generation_run_id" not in cols:
            op.add_column(
                "interview_questions",
                sa.Column("generation_run_id", sa.String(36), sa.ForeignKey("interview_generation_runs.id", ondelete="SET NULL")),
            )
            op.create_index("ix_interview_questions_generation_run_id", "interview_questions", ["generation_run_id"])
        if "superseded_at" not in cols:
            op.add_column("interview_questions", sa.Column("superseded_at", sa.DateTime()))

    if "interview_transcript_turns" not in tables:
        op.create_table(
            "interview_transcript_turns",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("session_id", sa.String(36), sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("question_id", sa.String(36), sa.ForeignKey("interview_questions.id", ondelete="SET NULL")),
            sa.Column("turn_type", sa.String(30), nullable=False),
            sa.Column("speaker", sa.String(20), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("audio_ref", sa.String(1000)),
            sa.Column("stt_confidence", sa.Float()),
            sa.Column("sequence_number", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_interview_transcript_turns_session_id", "interview_transcript_turns", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_interview_transcript_turns_session_id", table_name="interview_transcript_turns")
    op.drop_table("interview_transcript_turns")
    op.drop_index("ix_interview_questions_generation_run_id", table_name="interview_questions")
    op.drop_column("interview_questions", "superseded_at")
    op.drop_column("interview_questions", "generation_run_id")
    op.drop_index("ix_interview_generation_runs_input_snapshot_hash", table_name="interview_generation_runs")
    op.drop_index("ix_interview_generation_runs_application_id", table_name="interview_generation_runs")
    op.drop_table("interview_generation_runs")
