"""Add updated_at to portfolio_snapshot_item.

Posições Congeladas precisa ordenar por "quando ESTE item do snapshot
foi tocado por último", não por `asset.price_updated_at` (que é o
timestamp do preço corrente do asset — poluído por bulk refresh do
dashboard). Sem `updated_at` na tabela do item, a ordenação no IN_REVIEW
ficava na ordem em que o bulk refresh varreu os assets — aleatória pro
usuário.

Backfill: copia `created_at` pra `updated_at` em linhas existentes.
SQLite exige `batch_alter_table` pra alterar nullability.

Backup: `cp numis_geek.db numis_geek.db.bak-before-snapshot-item-updated-at`.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "e1a2b3c4d5e6"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("portfolio_snapshot_item") as batch:
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.execute(
        "UPDATE portfolio_snapshot_item "
        "SET updated_at = created_at WHERE updated_at IS NULL"
    )
    # Where a pendency was already resolved against this item, lift
    # `updated_at` to the resolution timestamp so historical "I just
    # fixed this" still surfaces at the top of Posições Congeladas.
    op.execute(
        """
        UPDATE portfolio_snapshot_item AS psi
        SET updated_at = COALESCE((
            SELECT MAX(p.resolved_at)
            FROM snapshot_pendency p
            WHERE p.snapshot_id = psi.snapshot_id
              AND p.asset_id = psi.asset_id
              AND p.resolved_at IS NOT NULL
        ), psi.updated_at)
        WHERE EXISTS (
            SELECT 1 FROM snapshot_pendency p
            WHERE p.snapshot_id = psi.snapshot_id
              AND p.asset_id = psi.asset_id
              AND p.resolved_at IS NOT NULL
        )
        """
    )

    with op.batch_alter_table("portfolio_snapshot_item") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("portfolio_snapshot_item") as batch:
        batch.drop_column("updated_at")
