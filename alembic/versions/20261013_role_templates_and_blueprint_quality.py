"""Add role_templates table, job_postings template references and normalized seniority, and job_skills template links.

Revision ID: 20261013_role_templates_and_blueprint_quality
Revises: 20261013_blueprint_r2_enhancements
"""

from alembic import op
import sqlalchemy as sa


revision = "20261013_role_templates_and_blueprint_quality"
down_revision = "20261013_blueprint_r2_enhancements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 1. Create role_templates table
    if "role_templates" not in tables:
        op.create_table(
            "role_templates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("role_key", sa.String(50), nullable=False, unique=True, index=True),
            sa.Column("display_name", sa.String(150), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("default_duration_mins", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("default_interviewer_tone", sa.Text(), nullable=True),
            sa.Column("default_pacing", sa.String(50), nullable=False, server_default="Balanced"),
            sa.Column("suggested_certifications", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("skills", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("seniority_profiles", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("question_style_notes", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        )

    # 2. Update job_postings table
    if "job_postings" in tables:
        cols = {c["name"] for c in inspector.get_columns("job_postings")}
        if "role_key" not in cols:
            op.add_column("job_postings", sa.Column("role_key", sa.String(50), nullable=False, server_default="custom"))
        if "role_template_id" not in cols:
            op.add_column("job_postings", sa.Column("role_template_id", sa.String(36), sa.ForeignKey("role_templates.id", ondelete="SET NULL"), nullable=True))
        if "role_template_version" not in cols:
            op.add_column("job_postings", sa.Column("role_template_version", sa.Integer(), nullable=True))

        # Normalize seniority_level values on existing records:
        # e.g., 'Mid-Level (L4)' -> 'mid', 'Senior (L5)' -> 'senior', 'Entry-Level (L3)' -> 'entry', 'Lead' -> 'lead'
        op.execute("""
            UPDATE job_postings
            SET seniority_level = CASE
                WHEN LOWER(seniority_level) LIKE '%entry%' OR LOWER(seniority_level) LIKE '%intern%' OR LOWER(seniority_level) LIKE '%l3%' THEN 'entry'
                WHEN LOWER(seniority_level) LIKE '%senior%' OR LOWER(seniority_level) LIKE '%l5%' THEN 'senior'
                WHEN LOWER(seniority_level) LIKE '%lead%' OR LOWER(seniority_level) LIKE '%staff%' OR LOWER(seniority_level) LIKE '%l6%' THEN 'lead'
                ELSE 'mid'
            END;
        """)

    # 3. Update job_skills table
    if "job_skills" in tables:
        cols = {c["name"] for c in inspector.get_columns("job_skills")}
        if "template_skill_key" not in cols:
            op.add_column("job_skills", sa.Column("template_skill_key", sa.String(50), nullable=True))
        if "target_level_min" not in cols:
            op.add_column("job_skills", sa.Column("target_level_min", sa.String(10), nullable=True))
        if "target_level_max" not in cols:
            op.add_column("job_skills", sa.Column("target_level_max", sa.String(10), nullable=True))
        if "source" not in cols:
            op.add_column("job_skills", sa.Column("source", sa.String(20), nullable=False, server_default="recruiter"))

        # Backfill target levels on existing job_skills based on parent job's normalized seniority
        op.execute("""
            UPDATE job_skills js
            SET target_level_min = CASE
                    WHEN jp.seniority_level = 'entry' THEN 'L2'
                    WHEN jp.seniority_level = 'mid' THEN 'L3'
                    WHEN jp.seniority_level = 'senior' THEN 'L4'
                    WHEN jp.seniority_level = 'lead' THEN 'L4'
                    ELSE 'L3'
                END,
                target_level_max = CASE
                    WHEN jp.seniority_level = 'entry' THEN 'L3'
                    WHEN jp.seniority_level = 'mid' THEN 'L4'
                    WHEN jp.seniority_level = 'senior' THEN 'L5'
                    WHEN jp.seniority_level = 'lead' THEN 'L5'
                    ELSE 'L4'
                END
            FROM job_postings jp
            WHERE js.job_id = jp.id AND (js.target_level_min IS NULL OR js.target_level_max IS NULL);
        """)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "job_skills" in tables:
        cols = {c["name"] for c in inspector.get_columns("job_skills")}
        for col in ["source", "target_level_max", "target_level_min", "template_skill_key"]:
            if col in cols:
                op.drop_column("job_skills", col)

    if "job_postings" in tables:
        cols = {c["name"] for c in inspector.get_columns("job_postings")}
        for col in ["role_template_version", "role_template_id", "role_key"]:
            if col in cols:
                op.drop_column("job_postings", col)

    if "role_templates" in tables:
        op.drop_table("role_templates")
