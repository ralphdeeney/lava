"""Add owned projects, services and hashed expiring API credentials.

Unowned Phase00 rows remain preserved under a disabled quarantine identity. Downgrade
refuses to discard new control-plane records; export/archive separately before rollback.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None
LEGACY_OWNER_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute(
        sa.text("INSERT INTO users (id, name, is_active) VALUES (:id, :name, false)").bindparams(
            id=LEGACY_OWNER_ID, name="legacy-quarantine"
        )
    )
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("expires_at > created_at", name="ck_credentials_expiry"),
    )
    op.create_index("ix_api_credentials_user_id", "api_credentials", ["user_id"])
    op.add_column(
        "projects", sa.Column("description", sa.String(2000), nullable=False, server_default="")
    )
    op.add_column("projects", sa.Column("owner_id", sa.String(36), nullable=True))
    op.add_column(
        "projects",
        sa.Column("lifecycle_status", sa.String(20), nullable=False, server_default="active"),
    )
    op.add_column(
        "projects",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.execute(sa.text("UPDATE projects SET owner_id = :id").bindparams(id=LEGACY_OWNER_ID))
    op.alter_column("projects", "owner_id", nullable=False)
    op.create_foreign_key(
        "fk_projects_owner_id", "projects", "users", ["owner_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.drop_constraint("projects_name_key", "projects", type_="unique")
    op.create_unique_constraint("uq_projects_owner_name", "projects", ["owner_id", "name"])
    op.create_check_constraint(
        "ck_projects_lifecycle", "projects", "lifecycle_status IN ('active', 'archived')"
    )
    op.create_check_constraint("ck_projects_name", "projects", "length(trim(name)) > 0")
    op.create_table(
        "services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("service_type", sa.String(20), nullable=False),
        sa.Column("desired_state", sa.String(20), nullable=False, server_default="stopped"),
        sa.Column("resources", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "name", name="uq_services_project_name"),
        sa.CheckConstraint(
            "service_type IN ('web', 'api', 'worker', 'database')", name="ck_services_type"
        ),
        sa.CheckConstraint(
            "desired_state IN ('stopped', 'running', 'archived')", name="ck_services_state"
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_services_name"),
        sa.CheckConstraint(
            "jsonb_typeof(resources) = 'object' "
            "AND resources ? 'cpu' AND resources ? 'memory_mb' "
            "AND jsonb_typeof(resources->'cpu') = 'number' "
            "AND jsonb_typeof(resources->'memory_mb') = 'number' "
            "AND (resources->>'cpu')::numeric > 0 "
            "AND (resources->>'cpu')::numeric <= 16 "
            "AND (resources->>'memory_mb')::numeric >= 64 "
            "AND (resources->>'memory_mb')::numeric <= 65536 "
            "AND (resources->>'memory_mb')::numeric = "
            "trunc((resources->>'memory_mb')::numeric)",
            name="ck_services_resources",
        ),
    )
    op.create_index("ix_services_project_id", "services", ["project_id"])


def downgrade() -> None:
    connection = op.get_bind()
    has_data = connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM services) "
            "OR EXISTS(SELECT 1 FROM api_credentials) "
            "OR EXISTS(SELECT 1 FROM projects WHERE owner_id != :legacy) "
            "OR EXISTS(SELECT 1 FROM users WHERE id != :legacy)"
        ),
        {"legacy": LEGACY_OWNER_ID},
    ).scalar_one()
    if has_data:
        raise RuntimeError(
            "Downgrade refused: control-plane records require explicit data preservation"
        )
    op.drop_table("services")
    op.drop_constraint("uq_projects_owner_name", "projects", type_="unique")
    op.create_unique_constraint("projects_name_key", "projects", ["name"])
    op.drop_constraint("ck_projects_name", "projects", type_="check")
    op.drop_constraint("ck_projects_lifecycle", "projects", type_="check")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_constraint("fk_projects_owner_id", "projects", type_="foreignkey")
    for name in ("updated_at", "lifecycle_status", "owner_id", "description"):
        op.drop_column("projects", name)
    op.drop_table("api_credentials")
    op.drop_table("users")
