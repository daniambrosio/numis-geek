"""spec68b — remove the prototype category seed.

The 11 prototype categories were seeded by 5d434d18c0a2 by mistake:
the interview decision (spec 73) is that categories come EXCLUSIVELY
from the user's Notion import — the table must start empty.

Defensive delete: only rows matching the seeded names, with
created_by IS NULL (seed marker — API writes always set created_by),
root-level, and without children. User-created rows are never touched.

Revision ID: spec68b_no_seed
Revises: 5d434d18c0a2
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'spec68b_no_seed'
down_revision: Union[str, Sequence[str], None] = '5d434d18c0a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEEDED_NAMES = [
    "Renda", "Transferência", "Mercado", "Restaurante", "Transporte",
    "Casa", "Lazer", "Saúde", "Tecnologia", "Tarifas", "Viagens",
]


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "DELETE FROM category"
            " WHERE created_by IS NULL"
            "   AND parent_id IS NULL"
            "   AND name IN :names"
            "   AND id NOT IN (SELECT DISTINCT parent_id FROM category WHERE parent_id IS NOT NULL)"
        ).bindparams(sa.bindparam("names", expanding=True)),
        {"names": SEEDED_NAMES},
    )
    print(f"spec68b: removed {result.rowcount} seeded categories")


def downgrade() -> None:
    # Intentionally a no-op: the seed should never come back.
    pass
