"""Add fenced build artifact provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "build_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("deployment_id", sa.String(36), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("source_commit_sha", sa.String(64), nullable=False),
        sa.Column("configuration_revision", sa.Integer(), nullable=False),
        sa.Column("railpack_version", sa.String(40), nullable=False),
        sa.Column("buildkit_version", sa.String(40), nullable=False),
        sa.Column("image_digest", sa.String(71), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("deployment_id", "attempt", name="uq_build_artifact_attempt"),
        sa.CheckConstraint("attempt >= 1", name="ck_build_artifact_attempt"),
        sa.CheckConstraint(
            "image_digest ~ '^sha256:[0-9a-f]{64}$'", name="ck_build_artifact_digest"
        ),
    )


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT EXISTS(SELECT 1 FROM build_artifacts)")).scalar_one():
        raise RuntimeError("Downgrade refused: build provenance must be preserved")
    op.drop_table("build_artifacts")
