"""Add Job Interview Blueprints, Blueprint Sections, Expectations, Questions,
Candidate Personalizations, and Session Expectation Coverage tables and relations.

Revision ID: 20261013_job_interview_blueprints
Revises: 20261013_live_interview_and_evaluation
"""

from alembic import op
import sqlalchemy as sa


revision = "20261013_job_interview_blueprints"
down_revision = "20261013_live_interview_and_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. interview_blueprints
    if "interview_blueprints" not in tables:
        op.create_table(
            "interview_blueprints",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "job_id",
                sa.String(36),
                sa.ForeignKey("job_postings.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("version", sa.Integer(), server_default="1", nullable=False),
            sa.Column("status", sa.String(20), server_default="draft", nullable=False),
            sa.Column("total_duration_mins", sa.Integer(), server_default="20", nullable=False),
            sa.Column("active_skill_mins", sa.Float(), server_default="14.0", nullable=False),
            sa.Column("fixed_overhead_mins", sa.Float(), server_default="6.0", nullable=False),
            sa.Column(
                "approved_by",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("validation_report", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        )

    # 2. Add active_blueprint_id to job_postings
    if "job_postings" in tables:
        cols = {c["name"] for c in inspector.get_columns("job_postings")}
        if "active_blueprint_id" not in cols:
            op.add_column(
                "job_postings",
                sa.Column(
                    "active_blueprint_id",
                    sa.String(36),
                    sa.ForeignKey("interview_blueprints.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )

    # 3. blueprint_sections
    if "blueprint_sections" not in tables:
        op.create_table(
            "blueprint_sections",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "blueprint_id",
                sa.String(36),
                sa.ForeignKey("interview_blueprints.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("order_index", sa.Integer(), nullable=False),
            sa.Column("section_type", sa.String(50), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column(
                "skill_id",
                sa.String(36),
                sa.ForeignKey("job_skills.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("skill_name", sa.String(200), nullable=True),
            sa.Column("priority_tier", sa.String(20), nullable=True),
            sa.Column("allocated_minutes", sa.Float(), nullable=False),
            sa.Column("target_rubric_tier", sa.String(50), nullable=True),
            sa.Column("welcome_script", sa.Text(), nullable=True),
            sa.Column("closing_script", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        )

    # 4. blueprint_expectations
    if "blueprint_expectations" not in tables:
        op.create_table(
            "blueprint_expectations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "section_id",
                sa.String(36),
                sa.ForeignKey("blueprint_sections.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("order_index", sa.Integer(), nullable=False),
            sa.Column("expectation_text", sa.Text(), nullable=False),
            sa.Column("source_rubric_level", sa.String(20), nullable=True),
            sa.Column("importance", sa.String(20), server_default="core", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        )

    # 5. blueprint_questions
    if "blueprint_questions" not in tables:
        op.create_table(
            "blueprint_questions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "section_id",
                sa.String(36),
                sa.ForeignKey("blueprint_sections.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("order_index", sa.Integer(), nullable=False),
            sa.Column("question_role", sa.String(30), nullable=False),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("trigger_condition", sa.Text(), nullable=True),
            sa.Column("target_expectation_ids", sa.JSON(), nullable=True),
            sa.Column("word_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        )

    # 6. candidate_personalizations
    if "candidate_personalizations" not in tables:
        op.create_table(
            "candidate_personalizations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "application_id",
                sa.String(36),
                sa.ForeignKey("job_applications.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
                index=True,
            ),
            sa.Column(
                "blueprint_id",
                sa.String(36),
                sa.ForeignKey("interview_blueprints.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("intro_hook", sa.Text(), nullable=False),
            sa.Column("deep_dive_project", sa.JSON(), nullable=True),
            sa.Column("per_skill_probes", sa.JSON(), nullable=True),
            sa.Column("claims_to_verify", sa.JSON(), nullable=True),
            sa.Column("raw_model_response", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        )

    # 7. session_expectation_coverage
    if "session_expectation_coverage" not in tables:
        op.create_table(
            "session_expectation_coverage",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "session_id",
                sa.String(36),
                sa.ForeignKey("interview_sessions.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "expectation_id",
                sa.String(36),
                sa.ForeignKey("blueprint_expectations.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("status", sa.String(30), server_default="not_probed", nullable=False),
            sa.Column("evidence_turn_ids", sa.JSON(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        )

    # 8. interview_sessions updates
    if "interview_sessions" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_sessions")}
        if "blueprint_id" not in cols:
            op.add_column(
                "interview_sessions",
                sa.Column(
                    "blueprint_id",
                    sa.String(36),
                    sa.ForeignKey("interview_blueprints.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
        if "blueprint_version" not in cols:
            op.add_column(
                "interview_sessions",
                sa.Column("blueprint_version", sa.Integer(), nullable=True),
            )

    # 9. interview_questions updates
    if "interview_questions" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_questions")}
        if "section_id" not in cols:
            op.add_column(
                "interview_questions",
                sa.Column(
                    "section_id",
                    sa.String(36),
                    sa.ForeignKey("blueprint_sections.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
        if "blueprint_question_id" not in cols:
            op.add_column(
                "interview_questions",
                sa.Column(
                    "blueprint_question_id",
                    sa.String(36),
                    sa.ForeignKey("blueprint_questions.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
        if "kind" not in cols:
            op.add_column(
                "interview_questions",
                sa.Column("kind", sa.String(50), nullable=True),
            )
        if "personalization_context" not in cols:
            op.add_column(
                "interview_questions",
                sa.Column("personalization_context", sa.JSON(), nullable=True),
            )
        if "target_expectation_ids" not in cols:
            op.add_column(
                "interview_questions",
                sa.Column("target_expectation_ids", sa.JSON(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # interview_questions columns
    if "interview_questions" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_questions")}
        for col in ["target_expectation_ids", "personalization_context", "kind", "blueprint_question_id", "section_id"]:
            if col in cols:
                op.drop_column("interview_questions", col)

    # interview_sessions columns
    if "interview_sessions" in tables:
        cols = {c["name"] for c in inspector.get_columns("interview_sessions")}
        for col in ["blueprint_version", "blueprint_id"]:
            if col in cols:
                op.drop_column("interview_sessions", col)

    # job_postings active_blueprint_id
    if "job_postings" in tables:
        cols = {c["name"] for c in inspector.get_columns("job_postings")}
        if "active_blueprint_id" in cols:
            op.drop_column("job_postings", "active_blueprint_id")

    # Drop new tables
    for tbl in [
        "session_expectation_coverage",
        "candidate_personalizations",
        "blueprint_questions",
        "blueprint_expectations",
        "blueprint_sections",
        "interview_blueprints",
    ]:
        if tbl in tables:
            op.drop_table(tbl)
