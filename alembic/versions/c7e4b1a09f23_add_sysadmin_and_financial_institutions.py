"""add_sysadmin_and_financial_institutions

Revision ID: c7e4b1a09f23
Revises: ba0301775385
Create Date: 2026-05-02 12:00:00.000000

"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c7e4b1a09f23'
down_revision: Union[str, Sequence[str], None] = 'ba0301775385'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INSTITUTIONS = [
    ("Itaú Unibanco S.A.", "Itaú", "itau"),
    ("XP Investimentos S.A.", "XP", "xp"),
    ("Avenue Securities LLC", "Avenue", "avenue"),
    ("BTG Pactual S.A.", "BTG", "btg"),
    ("Banco Bradesco S.A.", "Bradesco", "bradesco"),
    ("Banco Santander Brasil S.A.", "Santander", "santander"),
    ("Mercado Pago S.A.", "Mercado Pago", "mercadopago"),
    ("Wise Payments Ltd.", "Wise", "wise"),
    ("Coinbase Global Inc.", "Coinbase", "coinbase"),
    ("Clear Corretora", "Clear", "clear"),
    ("Caixa Econômica Federal", "Caixa", "caixa"),
]


def upgrade() -> None:
    # Make user.workspace_id nullable (sysadmin users have no workspace)
    with op.batch_alter_table("user") as batch_op:
        batch_op.alter_column("workspace_id", nullable=True)

    # Add sysadmin to the UserRole enum
    with op.batch_alter_table("user") as batch_op:
        batch_op.alter_column(
            "role",
            type_=sa.Enum("sysadmin", "admin", "member", name="userrole"),
            existing_nullable=False,
        )

    op.create_table(
        "financial_institution",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("long_name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=100), nullable=False),
        sa.Column("logo_slug", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    fi_table = sa.table(
        "financial_institution",
        sa.column("id", sa.String),
        sa.column("long_name", sa.String),
        sa.column("short_name", sa.String),
        sa.column("logo_slug", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(fi_table, [
        {
            "id": str(uuid.uuid4()),
            "long_name": long_name,
            "short_name": short_name,
            "logo_slug": logo_slug,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
        for long_name, short_name, logo_slug in INSTITUTIONS
    ])


def downgrade() -> None:
    op.drop_table("financial_institution")

    with op.batch_alter_table("user") as batch_op:
        batch_op.alter_column(
            "role",
            type_=sa.Enum("admin", "member", name="userrole"),
            existing_nullable=False,
        )

    with op.batch_alter_table("user") as batch_op:
        batch_op.alter_column("workspace_id", nullable=False)
