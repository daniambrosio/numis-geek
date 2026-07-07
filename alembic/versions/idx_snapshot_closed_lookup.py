"""index for _last_closed_snapshot_value lookup

Batch C do audit 2026-07-05/07 — a query em positions.py
_last_closed_snapshot_value filtra PortfolioSnapshot em (status,
is_active, period_end_date) e ORDER BY period_end_date DESC. Nenhum
index cobre esse pattern hoje (ix_snapshot_workspace_period começa por
workspace_id, que não é filtro aqui). Sem esse index, cada dashboard
load de value-mode assets faz table scan.

Revision ID: idx_snap_closed_lookup
Revises: att_snap_item
Create Date: 2026-07-07
"""

from alembic import op


revision = "idx_snap_closed_lookup"
down_revision = "att_snap_item"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_snapshot_closed_active_period",
        "portfolio_snapshot",
        ["status", "is_active", "period_end_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_snapshot_closed_active_period",
        table_name="portfolio_snapshot",
    )
