"""Add shared single-use WebSocket ticket consumption table.

Revision ID: 20261022_ws_ticket_single_use
Revises: 20261014_candidate_personalization_and_coverage
"""

from alembic import op
import sqlalchemy as sa


revision = "20261022_ws_ticket_single_use"
down_revision = "20261014_candidate_personalization_and_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "websocket_ticket_uses" in inspector.get_table_names():
        return

    op.create_table(
        "websocket_ticket_uses",
        sa.Column("ticket_id", sa.String(length=64), primary_key=True),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_websocket_ticket_uses_session_id",
        "websocket_ticket_uses",
        ["session_id"],
    )
    op.create_index(
        "ix_websocket_ticket_uses_user_id",
        "websocket_ticket_uses",
        ["user_id"],
    )
    op.create_index(
        "ix_websocket_ticket_uses_expires_at",
        "websocket_ticket_uses",
        ["expires_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "websocket_ticket_uses" in inspector.get_table_names():
        op.drop_table("websocket_ticket_uses")
