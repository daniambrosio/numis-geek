"""Spec 52 — add HISTORICAL_PRICE_REQUIRED to PendencyReason enum.

Quando o user adiciona um asset retroativamente a um snapshot antigo
(via Spec 51 recompute, ou via sync/add manual), o sistema não tem o
preço histórico daquele period_end. Em vez de escrever
asset.current_price (LIVE — corrompe o histórico), criamos uma pendency
com a reason nova HISTORICAL_PRICE_REQUIRED. User preenche manualmente
até a Spec 53 entregar o fetch histórico via providers.

Em SQLite enum é VARCHAR + CHECK constraint, então extender precisa de
`batch_alter_table`.

Backup: copy `numis_geek.db` to `numis_geek.db.bak-before-spec-52`
before upgrading.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "e2b3c4d5e6f7"
down_revision: str | None = "e1a2b3c4d5e6"
branch_labels = None
depends_on = None


REASON_OLD = sa.Enum(
    "API_FAILED", "MANUAL_SOURCE", "UPLOAD_REQUIRED", "STALE_PRICE",
    name="pendencyreason",
)
REASON_NEW = sa.Enum(
    "API_FAILED", "MANUAL_SOURCE", "UPLOAD_REQUIRED", "STALE_PRICE",
    "HISTORICAL_PRICE_REQUIRED",
    name="pendencyreason",
)


def upgrade() -> None:
    with op.batch_alter_table("snapshot_pendency") as batch:
        batch.alter_column(
            "reason",
            existing_type=REASON_OLD,
            type_=REASON_NEW,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("snapshot_pendency") as batch:
        batch.alter_column(
            "reason",
            existing_type=REASON_NEW,
            type_=REASON_OLD,
            existing_nullable=False,
        )
