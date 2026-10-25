"""Add password accounts, hashed browser sessions and shared login throttling."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_accounts",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "browser_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("expires_at > created_at", name="ck_browser_sessions_expiry"),
    )
    op.create_index("ix_browser_sessions_user_id", "browser_sessions", ["user_id"])
    op.create_index("ix_browser_sessions_expires_at", "browser_sessions", ["expires_at"])
    op.create_table(
        "login_attempts",
        sa.Column("bucket_hash", sa.String(64), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint("attempts > 0", name="ck_login_attempts_positive"),
    )
    op.create_index("ix_login_attempts_window_started_at", "login_attempts", ["window_started_at"])


def downgrade() -> None:
    has_records = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM password_accounts) "
                "OR EXISTS(SELECT 1 FROM browser_sessions)"
            )
        )
        .scalar_one()
    )
    if has_records:
        raise RuntimeError(
            "Downgrade refused: preserve password accounts and browser sessions first"
        )
    op.drop_table("login_attempts")
    op.drop_table("browser_sessions")
    op.drop_table("password_accounts")
