"""add created_by updated_by to existing tables

Revision ID: a1b2c3d4e5f6
Revises: c7e4b1a09f23
Create Date: 2026-05-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = 'c7e4b1a09f23'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("user", "workspace", "financial_institution"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("created_by", sa.String(36), nullable=True))
            batch.add_column(sa.Column("updated_by", sa.String(36), nullable=True))

    # workspace also needs updated_at (was missing)
    with op.batch_alter_table("workspace") as batch:
        batch.add_column(sa.Column("updated_at", sa.DateTime, nullable=True))

    conn = op.get_bind()
    row = conn.execute(sa.text("SELECT id FROM user WHERE role = 'sysadmin' LIMIT 1")).fetchone()
    if row:
        sysadmin_id = row[0]
        for table in ("user", "workspace", "financial_institution"):
            conn.execute(sa.text(
                f"UPDATE {table} SET created_by = :sid, updated_by = :sid"
            ), {"sid": sysadmin_id})
        # backfill workspace.updated_at from created_at
        conn.execute(sa.text("UPDATE workspace SET updated_at = created_at WHERE updated_at IS NULL"))


def downgrade() -> None:
    for table in ("user", "workspace", "financial_institution"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("created_by")
            batch.drop_column("updated_by")

    with op.batch_alter_table("workspace") as batch:
        batch.drop_column("updated_at")
