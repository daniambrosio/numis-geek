"""asset.account_id refactor + implicit accounts + drop CASH stubs

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-17 19:50:00.000000

Spec 10. Three coupled changes that all touch Asset's ownership chain:

1. DELETE 5 redundant CASH "Saldo em Conta (X)" stubs (zero lançamentos,
   pure metadata — float now lives on the InvestmentAccount itself).

2. INSERT 2 implicit investment accounts for FIs that hold orphan assets:
   - Particular → "Patrimônio pessoal" (BRL, investment)
   - Caixa → "Conta FGTS Caixa" (BRL, investment)

3. Replace `asset.financial_institution_id` with `asset.account_id`
   (FK to account, NOT NULL). Backfill: each asset's account_id is
   the investment account at its current (workspace, FI). The FI is
   reachable from any asset via `asset.account.financial_institution_id`.

Downgrade reverses each step. The 5 CASH stubs are NOT recreated on
downgrade — their data is gone for good (and was redundant by design).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


# (FI short_name, account_name, currency)
_IMPLICIT_ACCOUNTS = [
    ("Particular", "Patrimônio pessoal", "BRL"),
    ("Caixa", "Conta FGTS Caixa", "BRL"),
]


def _delete_cash_stubs() -> int:
    """DELETE asset rows where asset_class='CASH' AND name LIKE 'Saldo em Conta%'.

    These rows have zero lançamentos and represent broker float, which is
    redundant with the InvestmentAccount float in the new model.
    """
    bind = op.get_bind()
    res = bind.execute(sa.text(
        "DELETE FROM asset WHERE asset_class = 'CASH' AND name LIKE 'Saldo em Conta%'"
    ))
    return res.rowcount or 0


def _create_implicit_accounts() -> int:
    """For each (FI short_name, account_name, currency) in _IMPLICIT_ACCOUNTS,
    create an investment account in every workspace that has an asset at that FI
    but no investment account there. Idempotent.
    """
    bind = op.get_bind()
    created = 0
    now = datetime.now(timezone.utc)
    for fi_short, acc_name, ccy in _IMPLICIT_ACCOUNTS:
        fi_row = bind.execute(sa.text(
            "SELECT id FROM financial_institution WHERE short_name = :s"
        ), {"s": fi_short}).fetchone()
        if not fi_row:
            continue
        fi_id = fi_row.id
        # Workspaces that have an orphan asset at this FI
        rows = bind.execute(sa.text(
            """
            SELECT DISTINCT a.workspace_id
            FROM asset a
            WHERE a.financial_institution_id = :fi_id
              AND NOT EXISTS (
                SELECT 1 FROM account ac
                WHERE ac.workspace_id = a.workspace_id
                  AND ac.financial_institution_id = :fi_id
                  AND ac.account_type = 'investment'
              )
            """
        ), {"fi_id": fi_id}).fetchall()
        for r in rows:
            new_id = str(uuid.uuid4())
            bind.execute(sa.text(
                """
                INSERT INTO account (id, workspace_id, financial_institution_id, name,
                                     account_type, currency, opening_balance,
                                     account_info, is_active, created_at, updated_at,
                                     created_by, updated_by)
                VALUES (:id, :ws, :fi, :n, 'investment', :ccy, 0, NULL, 1,
                        :now, :now, NULL, NULL)
                """
            ), {
                "id": new_id, "ws": r.workspace_id, "fi": fi_id, "n": acc_name,
                "ccy": ccy, "now": now,
            })
            created += 1
    return created


def _backfill_account_id() -> None:
    """For each asset, set account_id = the investment account at the same
    (workspace, FI). After this every asset must have a non-null account_id.
    """
    bind = op.get_bind()
    bind.execute(sa.text(
        """
        UPDATE asset
        SET account_id = (
            SELECT ac.id
            FROM account ac
            WHERE ac.workspace_id = asset.workspace_id
              AND ac.financial_institution_id = asset.financial_institution_id
              AND ac.account_type = 'investment'
            LIMIT 1
        )
        """
    ))
    n_missing = bind.execute(sa.text(
        "SELECT COUNT(*) FROM asset WHERE account_id IS NULL"
    )).scalar()
    if n_missing:
        raise RuntimeError(
            f"{n_missing} assets still have NULL account_id after backfill — "
            "an FI may be missing its implicit investment account."
        )


def upgrade() -> None:
    # ── Step 1: drop the 5 CASH stubs ────────────────────────────────────────
    _delete_cash_stubs()

    # ── Step 2: create the 2 implicit investment accounts ───────────────────
    _create_implicit_accounts()

    # ── Step 3: add asset.account_id nullable ───────────────────────────────
    op.add_column("asset", sa.Column("account_id", sa.String(36), nullable=True))

    # ── Step 4: backfill account_id from (workspace, FI) ─────────────────────
    _backfill_account_id()

    # ── Step 5: drop the old unique index (refers to financial_institution_id) ──
    op.drop_index("ux_asset_workspace_ticker_fi", table_name="asset")

    # ── Step 6: NOT NULL on account_id + drop financial_institution_id ──────
    with op.batch_alter_table("asset") as batch_op:
        batch_op.alter_column("account_id", existing_type=sa.String(36), nullable=False)
        batch_op.create_foreign_key(
            "fk_asset_account",
            "account",
            ["account_id"], ["id"],
        )
        batch_op.drop_column("financial_institution_id")

    # ── Step 7: recreate the unique constraint against account_id ──────────
    op.create_index(
        "ux_asset_workspace_ticker_account",
        "asset",
        ["workspace_id", "ticker", "account_id"],
        unique=True,
        sqlite_where=sa.text("ticker IS NOT NULL"),
        postgresql_where=sa.text("ticker IS NOT NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()

    # ── Step 1: re-add financial_institution_id (nullable for backfill) ─────
    with op.batch_alter_table("asset") as batch_op:
        batch_op.add_column(sa.Column("financial_institution_id", sa.String(36), nullable=True))

    # ── Step 2: backfill from account.financial_institution_id ──────────────
    bind.execute(sa.text(
        """
        UPDATE asset
        SET financial_institution_id = (
            SELECT ac.financial_institution_id FROM account ac WHERE ac.id = asset.account_id
        )
        """
    ))

    # ── Step 3: drop the new account-based unique index ─────────────────────
    op.drop_index("ux_asset_workspace_ticker_account", table_name="asset")

    # ── Step 4: NOT NULL + drop account_id ──────────────────────────────────
    with op.batch_alter_table("asset") as batch_op:
        batch_op.alter_column(
            "financial_institution_id",
            existing_type=sa.String(36),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_asset_fi",
            "financial_institution",
            ["financial_institution_id"], ["id"],
        )
        batch_op.drop_constraint("fk_asset_account", type_="foreignkey")
        batch_op.drop_column("account_id")

    # ── Step 5: recreate the original unique index ──────────────────────────
    op.create_index(
        "ux_asset_workspace_ticker_fi",
        "asset",
        ["workspace_id", "ticker", "financial_institution_id"],
        unique=True,
        sqlite_where=sa.text("ticker IS NOT NULL"),
        postgresql_where=sa.text("ticker IS NOT NULL"),
    )

    # ── Step 4: delete the implicit accounts (no orphan FK now) ─────────────
    for fi_short, acc_name, _ccy in _IMPLICIT_ACCOUNTS:
        bind.execute(sa.text(
            """
            DELETE FROM account
            WHERE name = :n
              AND financial_institution_id = (
                SELECT id FROM financial_institution WHERE short_name = :s
              )
            """
        ), {"n": acc_name, "s": fi_short})

    # NOTE: the 5 CASH stubs deleted in upgrade() are NOT restored here —
    # their data was redundant by design. If a test needs them, recreate
    # via seed.
