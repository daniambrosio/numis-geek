"""add external_id/external_source on asset+lancamento, RESGATE_TOTAL enum, and nota_negociacao_number

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-04 12:00:00.000000

This migration lands four cross-cutting changes for spec 07c:

1. `LancamentoType` gains a 9th value `RESGATE_TOTAL`. SQLite stores enums as
   CHECK constraints embedded in the column DDL — we use `op.batch_alter_table`
   to recreate the column with the new constraint. Postgres uses the
   non-rewriting `ALTER TYPE ... ADD VALUE`.
2. New `ExternalSource` enum (NOTION/B3/BROKER_NOTE/MANUAL_CSV) — created on
   Postgres, no-op on SQLite (CHECK constraint is embedded in column DDL).
3. Adds `external_id`, `external_source` columns to `asset` AND `lancamento`,
   plus `nota_negociacao_number` to `lancamento`. Composite partial index
   `(external_source, external_id) WHERE external_id IS NOT NULL` on each.
4. Retroactively backfills `asset.external_id` / `asset.external_source` from
   the existing `notes` field — for any row whose `notes` starts with
   `"Notion: <url>"`, the URL is moved to `external_id`, source is set to
   `'NOTION'`, and the prefix is stripped from `notes`. Idempotent: skips
   rows whose `external_id` is already populated.

Downgrade reverses each step in dependency order, including restoring the
`Notion: ` prefix on `asset.notes` so no information is lost.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = 'a7b8c9d0e1f2'
down_revision: str | None = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


_OLD_LANCAMENTO_TYPE_VALUES = (
    'COMPRA',
    'VENDA',
    'DIVIDENDO',
    'JUROS',
    'JCP',
    'COME_COTAS',
    'BONIFICACAO',
    'SUBSCRICAO',
)
_NEW_LANCAMENTO_TYPE_VALUES = _OLD_LANCAMENTO_TYPE_VALUES + ('RESGATE_TOTAL',)

_EXTERNAL_SOURCE_VALUES = ('NOTION', 'B3', 'BROKER_NOTE', 'MANUAL_CSV')
_NOTION_PREFIX = "Notion: "


def _backfill_asset_external_id() -> None:
    """For every asset whose notes starts with 'Notion: <url>', extract the URL
    into external_id, set external_source='NOTION', and strip the prefix from
    notes. Skip rows whose external_id is already set (idempotent).
    """
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, notes FROM asset "
        "WHERE notes LIKE :pattern AND external_id IS NULL"
    ), {"pattern": f"{_NOTION_PREFIX}%"}).fetchall()

    for row in rows:
        notes = row.notes or ""
        if not notes.startswith(_NOTION_PREFIX):
            continue
        # The URL spans up to the first newline (or end of string).
        rest = notes[len(_NOTION_PREFIX):]
        nl = rest.find("\n")
        if nl == -1:
            url = rest.strip()
            remaining = ""
        else:
            url = rest[:nl].strip()
            remaining = rest[nl + 1:].lstrip("\n").strip()

        new_notes = remaining if remaining else None
        bind.execute(
            sa.text(
                "UPDATE asset SET external_id = :url, external_source = :src, notes = :notes "
                "WHERE id = :id"
            ),
            {"url": url, "src": "NOTION", "notes": new_notes, "id": row.id},
        )


def _restore_asset_notes_prefix() -> None:
    """Inverse of _backfill_asset_external_id: re-prepend 'Notion: <url>' to
    notes for every asset whose external_source='NOTION'. Used by downgrade
    so no information is lost on round-trip.
    """
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, notes, external_id FROM asset "
        "WHERE external_source = :src AND external_id IS NOT NULL"
    ), {"src": "NOTION"}).fetchall()
    for row in rows:
        url = row.external_id
        existing = (row.notes or "").strip()
        new_notes = f"{_NOTION_PREFIX}{url}" + (f"\n{existing}" if existing else "")
        bind.execute(
            sa.text("UPDATE asset SET notes = :notes WHERE id = :id"),
            {"notes": new_notes, "id": row.id},
        )


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'

    # ── Step 1: extend LancamentoType enum ───────────────────────────────────
    if is_postgres:
        op.execute("ALTER TYPE lancamentotype ADD VALUE IF NOT EXISTS 'RESGATE_TOTAL'")
    else:
        with op.batch_alter_table('lancamento') as batch_op:
            batch_op.alter_column(
                'type',
                existing_type=sa.Enum(*_OLD_LANCAMENTO_TYPE_VALUES, name='lancamentotype'),
                type_=sa.Enum(*_NEW_LANCAMENTO_TYPE_VALUES, name='lancamentotype'),
                existing_nullable=False,
            )

    # ── Step 2: create ExternalSource type (Postgres only) ───────────────────
    if is_postgres:
        op.execute(
            "DO $$ BEGIN "
            "CREATE TYPE externalsource AS ENUM ("
            + ", ".join(f"'{v}'" for v in _EXTERNAL_SOURCE_VALUES)
            + "); EXCEPTION WHEN duplicate_object THEN null; END $$;"
        )

    # ── Step 3: add columns to asset ─────────────────────────────────────────
    op.add_column(
        'asset',
        sa.Column('external_id', sa.String(255), nullable=True),
    )
    op.add_column(
        'asset',
        sa.Column(
            'external_source',
            sa.Enum(*_EXTERNAL_SOURCE_VALUES, name='externalsource'),
            nullable=True,
        ),
    )

    # ── Step 4: add columns to lancamento ────────────────────────────────────
    op.add_column(
        'lancamento',
        sa.Column('external_id', sa.String(255), nullable=True),
    )
    op.add_column(
        'lancamento',
        sa.Column(
            'external_source',
            sa.Enum(*_EXTERNAL_SOURCE_VALUES, name='externalsource'),
            nullable=True,
        ),
    )
    op.add_column(
        'lancamento',
        sa.Column('nota_negociacao_number', sa.String(50), nullable=True),
    )

    # ── Step 5: backfill asset.external_id from notes ('Notion: <url>') ──────
    _backfill_asset_external_id()

    # ── Step 6: partial composite indexes ────────────────────────────────────
    if is_postgres:
        op.create_index(
            'ix_asset_external',
            'asset',
            ['external_source', 'external_id'],
            postgresql_where=sa.text('external_id IS NOT NULL'),
        )
        op.create_index(
            'ix_lancamento_external',
            'lancamento',
            ['external_source', 'external_id'],
            postgresql_where=sa.text('external_id IS NOT NULL'),
        )
    else:
        # SQLite supports partial indexes via WHERE clause too
        op.create_index(
            'ix_asset_external',
            'asset',
            ['external_source', 'external_id'],
            sqlite_where=sa.text('external_id IS NOT NULL'),
        )
        op.create_index(
            'ix_lancamento_external',
            'lancamento',
            ['external_source', 'external_id'],
            sqlite_where=sa.text('external_id IS NOT NULL'),
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == 'postgresql'

    # ── Drop indexes first ───────────────────────────────────────────────────
    op.drop_index('ix_lancamento_external', table_name='lancamento')
    op.drop_index('ix_asset_external', table_name='asset')

    # ── Restore Notion: prefix on asset.notes BEFORE dropping columns ────────
    _restore_asset_notes_prefix()

    # ── Drop columns ─────────────────────────────────────────────────────────
    op.drop_column('lancamento', 'nota_negociacao_number')
    op.drop_column('lancamento', 'external_source')
    op.drop_column('lancamento', 'external_id')
    op.drop_column('asset', 'external_source')
    op.drop_column('asset', 'external_id')

    # ── Drop ExternalSource enum type (Postgres only) ────────────────────────
    if is_postgres:
        op.execute("DROP TYPE IF EXISTS externalsource")

    # ── Revert LancamentoType enum ───────────────────────────────────────────
    if is_postgres:
        # Postgres can't DROP a single enum value cleanly; recreate the type.
        op.execute("ALTER TYPE lancamentotype RENAME TO lancamentotype_old")
        op.execute(
            "CREATE TYPE lancamentotype AS ENUM ("
            + ", ".join(f"'{v}'" for v in _OLD_LANCAMENTO_TYPE_VALUES)
            + ")"
        )
        op.execute(
            "ALTER TABLE lancamento ALTER COLUMN type TYPE lancamentotype "
            "USING type::text::lancamentotype"
        )
        op.execute("DROP TYPE lancamentotype_old")
    else:
        with op.batch_alter_table('lancamento') as batch_op:
            batch_op.alter_column(
                'type',
                existing_type=sa.Enum(*_NEW_LANCAMENTO_TYPE_VALUES, name='lancamentotype'),
                type_=sa.Enum(*_OLD_LANCAMENTO_TYPE_VALUES, name='lancamentotype'),
                existing_nullable=False,
            )
