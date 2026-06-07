"""Spec 58 — extraction_job.institution_id

Adds nullable FK so bulk-extract jobs can be scoped to a single FI from
the upload point. Null on legacy jobs; new per-FI uploads carry it.

Revision ID: spec58_fi_id
Revises: e2b3c4d5e6f7
Create Date: 2026-06-07 17:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision: str = "spec58_fi_id"
down_revision: str | None = "e2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extraction_job") as batch:
        batch.add_column(
            sa.Column("institution_id", sa.String(length=36), nullable=True),
        )
        batch.create_foreign_key(
            "fk_extraction_job_institution",
            "financial_institution",
            ["institution_id"], ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("extraction_job") as batch:
        batch.drop_constraint("fk_extraction_job_institution", type_="foreignkey")
        batch.drop_column("institution_id")
