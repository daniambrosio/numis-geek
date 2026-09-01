"""fi logo upload — logo próprio + cor de marca por instituição financeira.

Até aqui o logo era 100% hardcoded no frontend (mapa slug→domínio pro favicon
do Google + paleta de cores em tokens.ts), então instituição nova nascia sem
logo e sem forma de editar. Passa a ser dado: arquivo em disco
(`data/fi-logos/{fi_id}.{ext}`) + hex da cor de marca na própria linha.

Revision ID: fi_logo_upload
Revises: 61c2a45f658e
Create Date: 2026-09-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fi_logo_upload'
down_revision: Union[str, Sequence[str], None] = '61c2a45f658e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Colunas nullable — add_column simples basta no SQLite.
    op.add_column('financial_institution', sa.Column('logo_storage_key', sa.String(255), nullable=True))
    op.add_column('financial_institution', sa.Column('logo_mime', sa.String(100), nullable=True))
    op.add_column('financial_institution', sa.Column('brand_color', sa.String(7), nullable=True))

    # Semeia brand_color com a paleta que vivia hardcoded em
    # frontend/src/lib/tokens.ts, pra não regredir as cores atuais.
    # Lowercase: é a forma normalizada que a API grava (normalize_hex_color).
    seed = {
        'xp': '#ffcb05',
        'avenue': '#0066ff',
        'itau': '#ec7000',
        'btg': '#0f2f4a',
        'bradesco': '#cc092f',
        'santander': '#ec0000',
        'caixa': '#0070af',
        'wise': '#9fe870',
        'coinbase': '#0052ff',
        'mercadopago': '#00b1ea',
        'clear': '#1faa59',
        'nubank': '#820ad1',
        'nomad': '#00e4b6',
        'particular': '#6b7280',
    }
    conn = op.get_bind()
    for slug, color in seed.items():
        conn.execute(
            sa.text(
                "UPDATE financial_institution SET brand_color = :c "
                "WHERE logo_slug = :s AND brand_color IS NULL"
            ),
            {"c": color, "s": slug},
        )


def downgrade() -> None:
    # SQLite: DROP COLUMN exige batch_alter_table (regra do repo).
    with op.batch_alter_table('financial_institution') as batch_op:
        batch_op.drop_column('brand_color')
        batch_op.drop_column('logo_mime')
        batch_op.drop_column('logo_storage_key')
