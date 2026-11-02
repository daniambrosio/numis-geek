"""spec 71c — category_example (exemplos de classificação do Notion)

Grupos de lançamentos categorizados no Notion, por texto do banco
normalizado — referência do System 1. Não são transações. Tabela nova,
nada existente muda.

Revision ID: spec71c_category_example
Revises: spec71b_system1_rule_alias
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa


revision = "spec71c_category_example"
down_revision = "spec71b_system1_rule_alias"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "category_example",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("alias_key", sa.String(length=255), nullable=False),
        sa.Column("sample_description", sa.String(length=255), nullable=True),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("avg_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("min_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("max_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["category.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "source", "alias_key", "category_id", "direction",
                            name="uq_category_example"),
    )
    op.create_index("ix_category_example_ws_key", "category_example", ["workspace_id", "alias_key"])


def downgrade() -> None:
    op.drop_index("ix_category_example_ws_key", table_name="category_example")
    op.drop_table("category_example")
