"""asset_movement rename + distribution split + drop Asset.subtype

Revision ID: b1a2c3d4e5f6
Revises: a7b8c9d0e1f2
Create Date: 2026-05-17 19:00:00.000000

Lands three coupled changes for spec 08:

1. Rename table `lancamento` → `asset_movement`, rename indexes, and rewrite
   the `type` enum: COMPRA→BUY, VENDA→SELL, BONIFICACAO→BONUS,
   SUBSCRICAO→SUBSCRIPTION, RESGATE_TOTAL→FULL_REDEMPTION; COME_COTAS stays;
   DIVIDENDO/JUROS/JCP are removed (they migrate to Distribution, but the
   local DB has zero rows of those types — `data check pre-upgrade` confirms).

2. Create new `distribution` table with 4 types: DIVIDEND, INTEREST, JCP,
   SECURITIES_LENDING. `asset_id` is nullable (Avenue's generic "rendimento
   de aluguel" has no ticker). `transaction_id` is intentionally NOT included
   here — Transaction entity arrives in spec 11.

3. Drop `asset.subtype` column. Before the drop, append every non-null
   subtype value to `asset.notes` with `[ex-subtype]` prefix so no
   information is lost.

Downgrade reverses everything.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "b1a2c3d4e5f6"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None

# Old (Portuguese) enum values used by `lancamento.type` pre-migration.
_OLD_LAN_VALUES = (
    "COMPRA", "VENDA", "DIVIDENDO", "JUROS", "JCP", "COME_COTAS",
    "BONIFICACAO", "SUBSCRICAO", "RESGATE_TOTAL",
)
# New (English) enum values used by `asset_movement.type` post-migration.
_NEW_AM_VALUES = (
    "BUY", "SELL", "COME_COTAS", "BONUS", "SUBSCRIPTION", "FULL_REDEMPTION",
)
# Mapping for preserved rows (income types must already be empty — guarded
# by a runtime check in upgrade()).
_OLD_TO_NEW = {
    "COMPRA": "BUY",
    "VENDA": "SELL",
    "BONIFICACAO": "BONUS",
    "SUBSCRICAO": "SUBSCRIPTION",
    "RESGATE_TOTAL": "FULL_REDEMPTION",
    "COME_COTAS": "COME_COTAS",
}

_DISTRIBUTION_VALUES = ("DIVIDEND", "INTEREST", "JCP", "SECURITIES_LENDING")
_EXTERNAL_SOURCE_VALUES = ("NOTION", "B3", "BROKER_NOTE", "MANUAL_CSV")


def _preserve_subtype_in_notes() -> None:
    """Append every non-null subtype value to notes with [ex-subtype] prefix."""
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, notes, subtype FROM asset "
        "WHERE subtype IS NOT NULL AND TRIM(subtype) != ''"
    )).fetchall()
    for row in rows:
        existing = (row.notes or "").rstrip()
        prefix = f"[ex-subtype] {row.subtype}"
        new_notes = (existing + "\n\n" + prefix) if existing else prefix
        bind.execute(
            sa.text("UPDATE asset SET notes = :notes WHERE id = :id"),
            {"notes": new_notes, "id": row.id},
        )


def _restore_subtype_from_notes() -> None:
    """Inverse: pull `[ex-subtype] X` line from notes back into the subtype column."""
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, notes FROM asset WHERE notes LIKE :pat"
    ), {"pat": "%[ex-subtype]%"}).fetchall()
    for row in rows:
        notes = row.notes or ""
        marker = "[ex-subtype] "
        idx = notes.find(marker)
        if idx == -1:
            continue
        after = notes[idx + len(marker):]
        nl = after.find("\n")
        subtype_value = after[:nl].strip() if nl != -1 else after.strip()
        # Strip the marker + value (and the preceding blank line if present)
        before = notes[:idx].rstrip("\n")
        rest = "" if nl == -1 else after[nl + 1:]
        cleaned = (before + ("\n" if before and rest else "") + rest).strip()
        bind.execute(
            sa.text("UPDATE asset SET subtype = :st, notes = :n WHERE id = :id"),
            {"st": subtype_value, "n": cleaned or None, "id": row.id},
        )


def _assert_no_income_rows() -> None:
    """Safety: refuse to drop DIVIDENDO/JUROS/JCP enum values if rows exist."""
    bind = op.get_bind()
    n = bind.execute(sa.text(
        "SELECT COUNT(*) FROM lancamento WHERE type IN ('DIVIDENDO', 'JUROS', 'JCP')"
    )).scalar()
    if n and int(n) > 0:
        raise RuntimeError(
            f"Refusing to migrate: {n} lancamento rows have type "
            "DIVIDENDO/JUROS/JCP. These belong in the new Distribution table — "
            "either move them manually or extend the migration."
        )


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ── Step 1: safety guard ─────────────────────────────────────────────────
    _assert_no_income_rows()

    # ── Step 2: preserve subtype values into notes ───────────────────────────
    _preserve_subtype_in_notes()

    # ── Step 3: drop ix_lancamento_external before rename (SQLite + PG) ──────
    op.drop_index("ix_lancamento_external", table_name="lancamento")

    # ── Step 4: rename table lancamento → asset_movement ─────────────────────
    op.rename_table("lancamento", "asset_movement")

    # ── Step 5: rewrite the type column (rename values + drop 3) ─────────────
    # First map old values to new ones for the rows we keep.
    when_clauses = " ".join(
        f"WHEN '{old}' THEN '{new}'" for old, new in _OLD_TO_NEW.items()
    )
    if is_postgres:
        # On Postgres, create the new enum, cast via text.
        op.execute(
            "CREATE TYPE assetmovementtype AS ENUM ("
            + ", ".join(f"'{v}'" for v in _NEW_AM_VALUES) + ")"
        )
        op.execute(
            "ALTER TABLE asset_movement ALTER COLUMN type TYPE assetmovementtype "
            f"USING (CASE type::text {when_clauses} END)::assetmovementtype"
        )
        op.execute("DROP TYPE lancamentotype")
    else:
        # SQLite: batch_alter_table recreates the table with the new enum
        # check constraint. First UPDATE the column to the new values.
        bind.execute(sa.text(
            f"UPDATE asset_movement SET type = CASE type {when_clauses} END"
        ))
        with op.batch_alter_table("asset_movement") as batch_op:
            batch_op.alter_column(
                "type",
                existing_type=sa.Enum(*_OLD_LAN_VALUES, name="lancamentotype"),
                type_=sa.Enum(*_NEW_AM_VALUES, name="assetmovementtype"),
                existing_nullable=False,
            )

    # ── Step 6: recreate indexes with new names ──────────────────────────────
    # The 3 non-partial indexes are auto-renamed by op.rename_table on Postgres
    # but stay with the old name on SQLite. Explicitly drop+recreate so both
    # backends end up with consistent names.
    for old in (
        "ix_lancamento_workspace_event_date",
        "ix_lancamento_asset_event_date",
        "ix_lancamento_workspace_type_event_date",
    ):
        try:
            op.drop_index(old, table_name="asset_movement")
        except Exception:
            pass  # name may already differ on Postgres after rename
    op.create_index(
        "ix_asset_movement_workspace_event_date",
        "asset_movement",
        ["workspace_id", "event_date"],
    )
    op.create_index(
        "ix_asset_movement_asset_event_date",
        "asset_movement",
        ["asset_id", "event_date"],
    )
    op.create_index(
        "ix_asset_movement_workspace_type_event_date",
        "asset_movement",
        ["workspace_id", "type", "event_date"],
    )
    # Recreate the partial external index with the new name.
    if is_postgres:
        op.create_index(
            "ix_asset_movement_external",
            "asset_movement",
            ["external_source", "external_id"],
            postgresql_where=sa.text("external_id IS NOT NULL"),
        )
    else:
        op.create_index(
            "ix_asset_movement_external",
            "asset_movement",
            ["external_source", "external_id"],
            sqlite_where=sa.text("external_id IS NOT NULL"),
        )

    # ── Step 7: create the distribution table ────────────────────────────────
    if is_postgres:
        op.execute(
            "CREATE TYPE distributiontype AS ENUM ("
            + ", ".join(f"'{v}'" for v in _DISTRIBUTION_VALUES) + ")"
        )
    op.create_table(
        "distribution",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column(
            "financial_institution_id",
            sa.String(36),
            sa.ForeignKey("financial_institution.id"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("asset.id"), nullable=True),
        sa.Column(
            "type",
            sa.Enum(*_DISTRIBUTION_VALUES, name="distributiontype"),
            nullable=False,
        ),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("tax", sa.Numeric(18, 2), nullable=True),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "currency",
            sa.Enum("BRL", "USD", name="currency"),
            nullable=False,
        ),
        sa.Column("fx_rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column(
            "external_source",
            sa.Enum(*_EXTERNAL_SOURCE_VALUES, name="externalsource"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
    )
    op.create_index("ix_distribution_workspace_event_date", "distribution", ["workspace_id", "event_date"])
    op.create_index("ix_distribution_fi_event_date", "distribution", ["financial_institution_id", "event_date"])
    op.create_index("ix_distribution_asset_event_date", "distribution", ["asset_id", "event_date"])
    if is_postgres:
        op.create_index(
            "ix_distribution_external",
            "distribution",
            ["external_source", "external_id"],
            postgresql_where=sa.text("external_id IS NOT NULL"),
        )
    else:
        op.create_index(
            "ix_distribution_external",
            "distribution",
            ["external_source", "external_id"],
            sqlite_where=sa.text("external_id IS NOT NULL"),
        )

    # ── Step 8: drop asset.subtype ───────────────────────────────────────────
    with op.batch_alter_table("asset") as batch_op:
        batch_op.drop_column("subtype")


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ── Step 1: re-add asset.subtype and restore from notes ──────────────────
    with op.batch_alter_table("asset") as batch_op:
        batch_op.add_column(sa.Column("subtype", sa.String(100), nullable=True))
    _restore_subtype_from_notes()

    # ── Step 2: drop distribution table + enum ───────────────────────────────
    op.drop_index("ix_distribution_external", table_name="distribution")
    op.drop_index("ix_distribution_asset_event_date", table_name="distribution")
    op.drop_index("ix_distribution_fi_event_date", table_name="distribution")
    op.drop_index("ix_distribution_workspace_event_date", table_name="distribution")
    op.drop_table("distribution")
    if is_postgres:
        op.execute("DROP TYPE distributiontype")

    # ── Step 3: drop new indexes on asset_movement ───────────────────────────
    op.drop_index("ix_asset_movement_external", table_name="asset_movement")
    op.drop_index("ix_asset_movement_workspace_type_event_date", table_name="asset_movement")
    op.drop_index("ix_asset_movement_asset_event_date", table_name="asset_movement")
    op.drop_index("ix_asset_movement_workspace_event_date", table_name="asset_movement")

    # ── Step 4: rewrite type enum back to Portuguese values ──────────────────
    new_to_old = {v: k for k, v in _OLD_TO_NEW.items()}
    when_clauses = " ".join(
        f"WHEN '{new}' THEN '{old}'" for new, old in new_to_old.items()
    )
    if is_postgres:
        op.execute(
            "CREATE TYPE lancamentotype AS ENUM ("
            + ", ".join(f"'{v}'" for v in _OLD_LAN_VALUES) + ")"
        )
        op.execute(
            "ALTER TABLE asset_movement ALTER COLUMN type TYPE lancamentotype "
            f"USING (CASE type::text {when_clauses} END)::lancamentotype"
        )
        op.execute("DROP TYPE assetmovementtype")
    else:
        bind.execute(sa.text(
            f"UPDATE asset_movement SET type = CASE type {when_clauses} END"
        ))
        with op.batch_alter_table("asset_movement") as batch_op:
            batch_op.alter_column(
                "type",
                existing_type=sa.Enum(*_NEW_AM_VALUES, name="assetmovementtype"),
                type_=sa.Enum(*_OLD_LAN_VALUES, name="lancamentotype"),
                existing_nullable=False,
            )

    # ── Step 5: rename table asset_movement → lancamento ─────────────────────
    op.rename_table("asset_movement", "lancamento")

    # ── Step 6: recreate old indexes on lancamento ───────────────────────────
    op.create_index(
        "ix_lancamento_workspace_event_date", "lancamento",
        ["workspace_id", "event_date"],
    )
    op.create_index(
        "ix_lancamento_asset_event_date", "lancamento",
        ["asset_id", "event_date"],
    )
    op.create_index(
        "ix_lancamento_workspace_type_event_date", "lancamento",
        ["workspace_id", "type", "event_date"],
    )
    if is_postgres:
        op.create_index(
            "ix_lancamento_external", "lancamento",
            ["external_source", "external_id"],
            postgresql_where=sa.text("external_id IS NOT NULL"),
        )
    else:
        op.create_index(
            "ix_lancamento_external", "lancamento",
            ["external_source", "external_id"],
            sqlite_where=sa.text("external_id IS NOT NULL"),
        )
