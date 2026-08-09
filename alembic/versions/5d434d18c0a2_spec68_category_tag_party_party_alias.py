"""spec68 category tag party party_alias

Spec 68 — expense-side registry tables: category (2-level, kind-typed),
tag, party, party_alias. Seeds the 11 prototype categories into every
existing workspace. Autogenerate drift on unrelated tables was stripped
by hand — this migration touches ONLY the four new tables.

Revision ID: 5d434d18c0a2
Revises: tesouro_integ_prov
Create Date: 2026-08-09 11:52:06.809826

"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d434d18c0a2'
down_revision: Union[str, Sequence[str], None] = 'tesouro_integ_prov'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_CATEGORIES = [
    # (name, kind, color) — colors match prototypes/index.html CATEGORIES
    ("Renda",         "INCOME",   "#22c55e"),
    ("Transferência", "TRANSFER", "#6366f1"),
    ("Mercado",       "EXPENSE",  "#84cc16"),
    ("Restaurante",   "EXPENSE",  "#f59e0b"),
    ("Transporte",    "EXPENSE",  "#3b82f6"),
    ("Casa",          "EXPENSE",  "#8b5cf6"),
    ("Lazer",         "EXPENSE",  "#ec4899"),
    ("Saúde",         "EXPENSE",  "#ef4444"),
    ("Tecnologia",    "EXPENSE",  "#14b8a6"),
    ("Tarifas",       "EXPENSE",  "#64748b"),
    ("Viagens",       "EXPENSE",  "#06b6d4"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('category',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('parent_id', sa.String(length=36), nullable=True),
        sa.Column('kind', sa.Enum('EXPENSE', 'INCOME', 'TRANSFER', name='categorykind'), nullable=False),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        sa.Column('updated_by', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['parent_id'], ['category.id'], ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ux_category_ws_parent_name', 'category', ['workspace_id', 'parent_id', 'name'], unique=True)

    op.create_table('party',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('kind', sa.Enum('SUPPLIER', 'CLIENT', 'BOTH', name='partykind'), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        sa.Column('updated_by', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_party_workspace_name', 'party', ['workspace_id', 'name'], unique=False)

    op.create_table('party_alias',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('party_id', sa.String(length=36), nullable=False),
        sa.Column('alias_normalized', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['party_id'], ['party.id'], ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_party_alias_party', 'party_alias', ['party_id'], unique=False)
    op.create_index('ux_party_alias_ws_alias', 'party_alias', ['workspace_id', 'alias_normalized'], unique=True)

    op.create_table('tag',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspace.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ux_tag_ws_name', 'tag', ['workspace_id', 'name'], unique=True)

    # ── seed: 11 prototype categories per existing workspace ──────────────────
    conn = op.get_bind()
    now = datetime.now(timezone.utc).isoformat(sep=' ')
    workspaces = conn.execute(sa.text("SELECT id FROM workspace")).fetchall()
    for (ws_id,) in workspaces:
        for name, kind, color in SEED_CATEGORIES:
            conn.execute(
                sa.text(
                    "INSERT INTO category (id, workspace_id, name, parent_id, kind, color,"
                    " is_active, created_at, updated_at, created_by, updated_by)"
                    " VALUES (:id, :ws, :name, NULL, :kind, :color, 1, :now, :now, NULL, NULL)"
                ),
                {"id": str(uuid.uuid4()), "ws": ws_id, "name": name, "kind": kind, "color": color, "now": now},
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ux_tag_ws_name', table_name='tag')
    op.drop_table('tag')
    op.drop_index('ux_party_alias_ws_alias', table_name='party_alias')
    op.drop_index('ix_party_alias_party', table_name='party_alias')
    op.drop_table('party_alias')
    op.drop_index('ix_party_workspace_name', table_name='party')
    op.drop_table('party')
    op.drop_index('ux_category_ws_parent_name', table_name='category')
    op.drop_table('category')
