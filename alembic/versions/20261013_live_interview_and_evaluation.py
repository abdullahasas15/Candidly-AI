"""Add live interview latency/coverage/resilience columns, evaluations, skill scores, integrity events, feedback, and drop legacy question score columns.

Revision ID: 20261013_live_interview_and_evaluation
Revises: 20261005_interview_generation_runtime
"""

from alembic import op
import sqlalchemy as sa


revision = "20261013_live_interview_and_evaluation"
down_revision = "20261005_interview_generation_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. job_applications: recruiter decision fields
    if "job_applications" in tables:
        cols = {c["name"] for c in inspector.get_columns("job_applications")}
        if "recruiter_decision" not in cols:
            op.add_column("job_applications", sa.Column("recruiter_decision", sa.String(30), nullable=True))
        if "recruiter_notes" not in cols:
            op.add_column("job_applications", sa.Column("recruiter_notes", sa.Text(), nullable=True))
        if "decided_by" not in cols:
            op.add_column("job_applications", sa.Column("decided_by", sa.String(36), nullable=True))
        if "decided_at" not in cols:
            op.add_column("job_applications", sa.Column("decided_at", sa.DateTime(), nullable=True))

    # 2. interview_sessions: brief, running summary, follow-up counter, settings, pause state
    if "interview_sessions" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_sessions")}
        if "interviewer_brief" not in cols:
            op.add_column("interview_sessions", sa.Column("interviewer_brief", sa.Text(), nullable=True))
        if "running_summary" not in cols:
            op.add_column("interview_sessions", sa.Column("running_summary", sa.Text(), nullable=True))
        if "follow_up_count_in_current" not in cols:
            op.add_column(
                "interview_sessions",
                sa.Column("follow_up_count_in_current", sa.Integer(), server_default="0", nullable=False),
            )
        if "speech_speed" not in cols:
            op.add_column(
                "interview_sessions",
                sa.Column("speech_speed", sa.Float(), server_default="1.0", nullable=False),
            )
        if "captions_enabled" not in cols:
            op.add_column(
                "interview_sessions",
                sa.Column("captions_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            )
        if "is_practice" not in cols:
            op.add_column(
                "interview_sessions",
                sa.Column("is_practice", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            )
        if "recording_consent" not in cols:
            op.add_column(
                "interview_sessions",
                sa.Column("recording_consent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            )
        if "recording_retention_days" not in cols:
            op.add_column(
                "interview_sessions",
                sa.Column("recording_retention_days", sa.Integer(), server_default="0", nullable=True),
            )
        if "paused_at" not in cols:
            op.add_column("interview_sessions", sa.Column("paused_at", sa.DateTime(), nullable=True))

    # 3. interview_questions: coverage, evidence, approval; drop legacy evaluation_score & evaluation_feedback
    if "interview_questions" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_questions")}
        if "skill_id" not in cols:
            op.add_column("interview_questions", sa.Column("skill_id", sa.String(36), nullable=True))
        if "question_state" not in cols:
            op.add_column(
                "interview_questions",
                sa.Column("question_state", sa.String(30), server_default="not_started", nullable=False),
            )
        if "coverage_status" not in cols:
            op.add_column("interview_questions", sa.Column("coverage_status", sa.JSON(), nullable=True))
        if "evidence_turn_ids" not in cols:
            op.add_column("interview_questions", sa.Column("evidence_turn_ids", sa.JSON(), nullable=True))
        if "approved_by_recruiter" not in cols:
            op.add_column(
                "interview_questions",
                sa.Column("approved_by_recruiter", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            )
        if "evaluation_score" in cols:
            op.drop_column("interview_questions", "evaluation_score")
        if "evaluation_feedback" in cols:
            op.drop_column("interview_questions", "evaluation_feedback")

    # 4. interview_transcript_turns: interruption tracking & per-stage latency_ms columns
    if "interview_transcript_turns" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_transcript_turns")}
        if "spoken_text" not in cols:
            op.add_column("interview_transcript_turns", sa.Column("spoken_text", sa.Text(), nullable=True))
        if "was_interrupted" not in cols:
            op.add_column(
                "interview_transcript_turns",
                sa.Column("was_interrupted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            )
        if "stt_final_ms" not in cols:
            op.add_column("interview_transcript_turns", sa.Column("stt_final_ms", sa.Float(), nullable=True))
        if "llm_ttft_ms" not in cols:
            op.add_column("interview_transcript_turns", sa.Column("llm_ttft_ms", sa.Float(), nullable=True))
        if "tts_first_audio_ms" not in cols:
            op.add_column("interview_transcript_turns", sa.Column("tts_first_audio_ms", sa.Float(), nullable=True))
        if "total_response_ms" not in cols:
            op.add_column("interview_transcript_turns", sa.Column("total_response_ms", sa.Float(), nullable=True))

    # 5. interview_evaluations
    if "interview_evaluations" not in tables:
        op.create_table(
            "interview_evaluations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "session_id",
                sa.String(36),
                sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "application_id",
                sa.String(36),
                sa.ForeignKey("job_applications.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "job_id",
                sa.String(36),
                sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("overall_score", sa.Float(), nullable=True),
            sa.Column("verdict", sa.String(30), nullable=True),
            sa.Column("insufficient_evidence", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("p0_not_assessed_skills", sa.JSON(), nullable=True),
            sa.Column("second_pass_triggered", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("strengths", sa.JSON(), nullable=True),
            sa.Column("concerns", sa.JSON(), nullable=True),
            sa.Column("candidate_summary", sa.Text(), nullable=True),
            sa.Column("model_name", sa.String(100), nullable=False, server_default="gemini-3.5-flash"),
            sa.Column("prompt_version", sa.String(50), nullable=False, server_default="v1"),
            sa.Column("token_usage_json", sa.JSON(), nullable=True),
            sa.Column("raw_response_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_interview_evaluations_session_id", "interview_evaluations", ["session_id"])
        op.create_index("ix_interview_evaluations_application_id", "interview_evaluations", ["application_id"])
        op.create_index("ix_interview_evaluations_job_id", "interview_evaluations", ["job_id"])

    # 6. interview_skill_scores
    if "interview_skill_scores" not in tables:
        op.create_table(
            "interview_skill_scores",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "evaluation_id",
                sa.String(36),
                sa.ForeignKey("interview_evaluations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("skill_id", sa.String(36), nullable=True),
            sa.Column("skill_name", sa.String(255), nullable=False),
            sa.Column("priority_tier", sa.String(10), nullable=False, server_default="P0"),
            sa.Column("weight_percentage", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("level", sa.String(20), nullable=False, server_default="NOT_ASSESSED"),
            sa.Column("numeric_score", sa.Float(), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column("verified_quote_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unverified_quote_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("low_confidence_warning", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_interview_skill_scores_evaluation_id", "interview_skill_scores", ["evaluation_id"])

    # 7. interview_integrity_events
    if "interview_integrity_events" not in tables:
        op.create_table(
            "interview_integrity_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "session_id",
                sa.String(36),
                sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "application_id",
                sa.String(36),
                sa.ForeignKey("job_applications.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False, server_default="low"),
            sa.Column("policy_tier", sa.String(30), nullable=False, server_default="Moderate"),
            sa.Column("details_json", sa.JSON(), nullable=True),
            sa.Column(
                "turn_id",
                sa.String(36),
                sa.ForeignKey("interview_transcript_turns.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_interview_integrity_events_session_id", "interview_integrity_events", ["session_id"])
        op.create_index(
            "ix_interview_integrity_events_application_id", "interview_integrity_events", ["application_id"]
        )

    # 8. interview_feedback
    if "interview_feedback" not in tables:
        op.create_table(
            "interview_feedback",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "session_id",
                sa.String(36),
                sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "application_id",
                sa.String(36),
                sa.ForeignKey("job_applications.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("candidate_id", sa.String(36), nullable=True),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_interview_feedback_session_id", "interview_feedback", ["session_id"])
        op.create_index("ix_interview_feedback_application_id", "interview_feedback", ["application_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "interview_feedback" in tables:
        op.drop_table("interview_feedback")
    if "interview_integrity_events" in tables:
        op.drop_table("interview_integrity_events")
    if "interview_skill_scores" in tables:
        op.drop_table("interview_skill_scores")
    if "interview_evaluations" in tables:
        op.drop_table("interview_evaluations")

    if "interview_transcript_turns" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_transcript_turns")}
        for col in ["total_response_ms", "tts_first_audio_ms", "llm_ttft_ms", "stt_final_ms", "was_interrupted", "spoken_text"]:
            if col in cols:
                op.drop_column("interview_transcript_turns", col)

    if "interview_questions" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_questions")}
        if "evaluation_score" not in cols:
            op.add_column("interview_questions", sa.Column("evaluation_score", sa.Float(), nullable=True))
        if "evaluation_feedback" not in cols:
            op.add_column("interview_questions", sa.Column("evaluation_feedback", sa.Text(), nullable=True))
        for col in ["approved_by_recruiter", "evidence_turn_ids", "coverage_status", "question_state", "skill_id"]:
            if col in cols:
                op.drop_column("interview_questions", col)

    if "interview_sessions" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_sessions")}
        for col in [
            "paused_at",
            "recording_retention_days",
            "recording_consent",
            "is_practice",
            "captions_enabled",
            "speech_speed",
            "follow_up_count_in_current",
            "running_summary",
            "interviewer_brief",
        ]:
            if col in cols:
                op.drop_column("interview_sessions", col)

    if "job_applications" in tables:
        cols = {c["name"] for c in inspector.get_columns("job_applications")}
        for col in ["decided_at", "decided_by", "recruiter_notes", "recruiter_decision"]:
            if col in cols:
                op.drop_column("job_applications", col)
