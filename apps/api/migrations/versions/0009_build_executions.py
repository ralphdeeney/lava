"""Durable build execution identity and request replay prevention."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "build_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("deployment_id", sa.String(36), nullable=False),
        sa.Column("claim_generation", sa.Integer(), nullable=False),
        sa.Column("source_commit_sha", sa.String(40), nullable=False),
        sa.Column("configuration_revision", sa.Integer(), nullable=False),
        sa.Column("fixture", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="UNKNOWN"),
        sa.Column("image_digest", sa.String(71)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["job_id"], ["deployment_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("job_id", "claim_generation", name="uq_build_execution_claim"),
        sa.CheckConstraint(
            "status IN ('UNKNOWN','RUNNING','COMPLETED','CANCELLED','FAILED')",
            name="ck_build_execution_status",
        ),
    )
    op.create_table(
        "build_request_nonces",
        sa.Column("nonce_hash", sa.String(64), primary_key=True),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["build_executions.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_build_request_nonces_expiry", "build_request_nonces", ["expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("build_request_nonces", "build_executions"):
        if bind.execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM {table})")).scalar_one():
            raise RuntimeError("Downgrade refused: build execution history must be preserved")
    op.drop_index("ix_build_request_nonces_expiry", table_name="build_request_nonces")
    op.drop_table("build_request_nonces")
    op.drop_table("build_executions")
