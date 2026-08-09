"""spec68c — kind só na subcategoria; raiz vira agrupador puro.

Decisão do user 2026-08-09 (v2, substitui o modelo kind-na-raiz+override):
`category.kind` passa a ser nullable; raízes ficam com kind NULL (são só
agrupadores temáticos com nome+cor); toda subcategoria carrega o próprio
kind, e é ele que classifica a transação (spec 74). Transaction (spec 70)
passará a exigir category_id apontando pra SUBcategoria.

Revision ID: spec68c_kind_sub
Revises: spec68b_no_seed
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'spec68c_kind_sub'
down_revision: Union[str, Sequence[str], None] = 'spec68b_no_seed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite: mudança de nullability exige batch_alter_table (regra do repo).
    with op.batch_alter_table('category') as batch_op:
        batch_op.alter_column(
            'kind',
            existing_type=sa.Enum('EXPENSE', 'INCOME', 'TRANSFER', name='categorykind'),
            nullable=True,
        )
    # Raízes existentes viram agrupadores puros.
    op.execute("UPDATE category SET kind = NULL WHERE parent_id IS NULL")


def downgrade() -> None:
    # Restaura NOT NULL dando às raízes um kind derivado (EXPENSE como
    # default conservador — o modelo antigo não é recuperável fielmente).
    op.execute("UPDATE category SET kind = 'EXPENSE' WHERE kind IS NULL")
    with op.batch_alter_table('category') as batch_op:
        batch_op.alter_column(
            'kind',
            existing_type=sa.Enum('EXPENSE', 'INCOME', 'TRANSFER', name='categorykind'),
            nullable=False,
        )
