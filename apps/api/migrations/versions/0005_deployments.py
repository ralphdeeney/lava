"""Add durable deployment metadata and transition history."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_services_project_id", "services", ["project_id", "id"])
    op.create_table(
        "deployments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("environment_id", sa.String(36), nullable=False),
        sa.Column("service_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("repository_url", sa.String(2048), nullable=False, server_default=""),
        sa.Column("source_commit_sha", sa.String(64), nullable=False),
        sa.Column("source_branch", sa.String(200), nullable=False),
        sa.Column("image_digest", sa.String(255)),
        sa.Column("configuration_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("failure_message", sa.String(500)),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["environment_id"], ["environments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["project_id", "environment_id"],
            ["environments.project_id", "environments.id"],
            name="fk_deployment_environment_same_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "service_id"],
            ["services.project_id", "services.id"],
            name="fk_deployment_service_same_project",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id", "service_id", "idempotency_key", name="uq_deployment_idempotency"
        ),
        sa.CheckConstraint("source_type IN ('git','image')", name="ck_deployment_source_type"),
        sa.CheckConstraint(
            "status IN ('queued','building','built','deploying','verifying','active',"
            "'failed','cancelled','rolled_back')",
            name="ck_deployment_status",
        ),
        sa.CheckConstraint(
            "source_commit_sha ~ '^[0-9a-fA-F]{7,64}$'", name="ck_deployment_commit_sha"
        ),
        sa.CheckConstraint("configuration_revision >= 1", name="ck_deployment_config_revision"),
    )
    op.create_index("ix_deployments_status_created", "deployments", ["status", "created_at"])
    op.create_index("ix_deployments_service_created", "deployments", ["service_id", "created_at"])
    op.create_table(
        "deployment_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("deployment_id", sa.String(36), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("message", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_deployment_events_deployment_created",
        "deployment_events",
        ["deployment_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_deployment_events_deployment_created", table_name="deployment_events")
    op.drop_table("deployment_events")
    op.drop_index("ix_deployments_service_created", table_name="deployments")
    op.drop_index("ix_deployments_status_created", table_name="deployments")
    op.drop_table("deployments")
    op.drop_constraint("uq_services_project_id", "services", type_="unique")
