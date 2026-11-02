"""spec 71b — System 1 (classificação por LLM) + aliases aprendidos de regra

- `extraction_job.classification_json` (JSON nullable): resultado persistido
  do passo "System 1" (categoria sugerida, ocorrência e motivo por linha).
- tabela `recurrence_rule_alias`: texto do banco (descrição normalizada ou
  contraparte do Pix) que já quitou uma regra — sinal forte do matcher de
  contas a pagar/receber.

Aditivo; nenhuma row existente muda. SQLite: add column via batch_alter_table.

Revision ID: spec71b_system1_rule_alias
Revises: spec71_statement_import
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa


revision = "spec71b_system1_rule_alias"
down_revision = "spec71_statement_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extraction_job") as batch:
        batch.add_column(sa.Column("classification_json", sa.JSON(), nullable=True))

    op.create_table(
        "recurrence_rule_alias",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("recurrence_rule_id", sa.String(length=36), nullable=False),
        sa.Column("alias_normalized", sa.String(length=255), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.ForeignKeyConstraint(["recurrence_rule_id"], ["recurrence_rule.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recurrence_rule_id", "alias_normalized", name="uq_rule_alias"),
    )
    op.create_index("ix_rule_alias_ws_alias", "recurrence_rule_alias", ["workspace_id", "alias_normalized"])


def downgrade() -> None:
    op.drop_index("ix_rule_alias_ws_alias", table_name="recurrence_rule_alias")
    op.drop_table("recurrence_rule_alias")
    with op.batch_alter_table("extraction_job") as batch:
        batch.drop_column("classification_json")
