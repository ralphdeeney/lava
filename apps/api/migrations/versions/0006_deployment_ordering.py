"""Add versioned transitions and monotonic deployment event ordering."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deployments",
        sa.Column("transition_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_deployment_transition_version", "deployments", "transition_version >= 0"
    )
    op.add_column("deployment_events", sa.Column("sequence", sa.Integer(), nullable=True))
    op.execute(sa.text("UPDATE deployment_events SET sequence = 0 WHERE sequence IS NULL"))
    op.alter_column("deployment_events", "sequence", nullable=False)
    op.create_unique_constraint(
        "uq_deployment_event_sequence", "deployment_events", ["deployment_id", "sequence"]
    )


def downgrade() -> None:
    connection = op.get_bind()
    used = connection.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM deployments) OR EXISTS(SELECT 1 FROM deployment_events)"
        )
    ).scalar_one()
    if used:
        raise RuntimeError("Downgrade refused: preserve deployment state and event history first")
    op.drop_constraint("uq_deployment_event_sequence", "deployment_events", type_="unique")
    op.drop_column("deployment_events", "sequence")
    op.drop_constraint("ck_deployment_transition_version", "deployments", type_="check")
    op.drop_column("deployments", "transition_version")
