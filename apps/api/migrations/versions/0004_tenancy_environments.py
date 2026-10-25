"""Add project memberships, identity-bound invitations and environment metadata.

Existing owners become active Owner members. Service configuration is additive; all
existing services keep their previous resources and start without an environment.
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column("lifecycle_status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "slug", name="uq_environment_project_slug"),
        sa.UniqueConstraint("project_id", "id", name="uq_environment_project_id"),
        sa.CheckConstraint(
            "lifecycle_status IN ('active','archived')", name="ck_environment_lifecycle"
        ),
        sa.CheckConstraint("slug ~ '^[a-z][a-z0-9-]{0,99}$'", name="ck_environment_slug"),
    )
    op.create_index("ix_environments_project_id", "environments", ["project_id"])
    op.create_table(
        "project_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_membership_project_user"),
        sa.CheckConstraint(
            "role IN ('owner','admin','developer','viewer')", name="ck_membership_role"
        ),
        sa.CheckConstraint("status IN ('active','revoked')", name="ck_membership_status"),
        sa.CheckConstraint(
            "(status='active' AND revoked_at IS NULL) OR "
            "(status='revoked' AND revoked_at IS NOT NULL)",
            name="ck_membership_revocation",
        ),
    )
    op.create_index("ix_membership_user_status", "project_memberships", ["user_id", "status"])
    op.execute(
        sa.text(
            "INSERT INTO project_memberships (id, project_id, user_id, role, status) "
            "SELECT gen_random_uuid()::text, id, owner_id, 'owner', 'active' FROM projects"
        )
    )
    op.create_table(
        "project_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("invitee_id", sa.String(36), nullable=False),
        sa.Column("inviter_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invitee_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inviter_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("role IN ('admin','developer','viewer')", name="ck_invitation_role"),
        sa.CheckConstraint(
            "status IN ('pending','accepted','declined','revoked','expired')",
            name="ck_invitation_status",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_invitation_expiry"),
    )
    op.create_index("ix_invitation_project_status", "project_invitations", ["project_id", "status"])
    op.create_index("ix_invitation_invitee_status", "project_invitations", ["invitee_id", "status"])
    op.create_index(
        "uq_pending_invitation_project_invitee",
        "project_invitations",
        ["project_id", "invitee_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.add_column("services", sa.Column("environment_id", sa.String(36), nullable=True))
    op.add_column(
        "services",
        sa.Column("build_method", sa.String(20), nullable=False, server_default="railpack"),
    )
    op.add_column(
        "services", sa.Column("start_command", sa.String(500), nullable=False, server_default="")
    )
    op.add_column(
        "services",
        sa.Column("deployment_branch", sa.String(200), nullable=False, server_default="main"),
    )
    op.add_column(
        "services", sa.Column("config_revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "services", sa.Column("desired_replicas", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_foreign_key(
        "fk_services_environment_id",
        "services",
        "environments",
        ["environment_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_service_environment_same_project",
        "services",
        "environments",
        ["project_id", "environment_id"],
        ["project_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_services_environment_id", "services", ["environment_id"])
    op.create_check_constraint(
        "ck_services_build_method",
        "services",
        "build_method IN ('railpack', 'dockerfile', 'image')",
    )
    op.create_check_constraint("ck_services_config_revision", "services", "config_revision >= 1")
    op.create_check_constraint(
        "ck_services_desired_replicas", "services", "desired_replicas BETWEEN 0 AND 10"
    )


def downgrade() -> None:
    connection = op.get_bind()
    used = connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM environments) "
            "OR EXISTS(SELECT 1 FROM project_invitations) "
            "OR EXISTS(SELECT 1 FROM project_memberships m "
            "JOIN projects p ON p.id=m.project_id "
            "WHERE m.user_id != p.owner_id OR m.role != 'owner' OR m.status != 'active') "
            "OR EXISTS(SELECT 1 FROM services WHERE environment_id IS NOT NULL "
            "OR build_method != 'railpack' OR start_command != '' "
            "OR deployment_branch != 'main' OR config_revision != 1 OR desired_replicas != 1)"
        )
    ).scalar_one()
    if used:
        raise RuntimeError(
            "Downgrade refused: preserve membership, invitation, environment "
            "and service configuration data first"
        )
    for name in (
        "ck_services_desired_replicas",
        "ck_services_config_revision",
        "ck_services_build_method",
    ):
        op.drop_constraint(name, "services", type_="check")
    op.drop_index("ix_services_environment_id", table_name="services")
    op.drop_constraint("fk_service_environment_same_project", "services", type_="foreignkey")
    op.drop_constraint("fk_services_environment_id", "services", type_="foreignkey")
    for name in (
        "desired_replicas",
        "config_revision",
        "deployment_branch",
        "start_command",
        "build_method",
        "environment_id",
    ):
        op.drop_column("services", name)
    op.drop_table("project_invitations")
    op.drop_table("project_memberships")
    op.drop_table("environments")
