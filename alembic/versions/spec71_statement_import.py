"""spec 71 — import de extrato/fatura: content_hash, extraction_job_id, enums

Spec 71 — Import de extrato e fatura com detecção de duplicatas.

- `attachment.content_hash` (SHA-256) + índice (workspace_id, content_hash)
  — dedup camada 1. Backfill dos anexos existentes lendo o arquivo do disco
  (`data/attachments/{storage_key}`); arquivo ausente fica NULL.
- `attachment.source_type` ganha `account` e `credit_card_account`.
- `extraction_job` ganha `checking_account_id`, `credit_card_account_id`,
  `statement_period_start/end`; `source_hint`/`detected_hint` ganham
  `BANK_STATEMENT` e `CARD_INVOICE`.
- `transaction.extraction_job_id` (FK nullable, indexado) — rastreabilidade
  arquivo → transação; `transaction.fingerprint` vai de 40 pra 48 chars
  (sufixo `:k` de linha idêntica promovida no review).

Tudo aditivo — nenhuma row existente muda além do backfill do hash.
SQLite: troca de enum e FK nova exigem batch_alter_table.

Revision ID: spec71_statement_import
Revises: spec72_slot_date
Create Date: 2026-10-31
"""
import hashlib
import os
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "spec71_statement_import"
down_revision = "spec72_slot_date"
branch_labels = None
depends_on = None


SOURCE_OLD = sa.Enum(
    "asset", "movement", "distribution", "snapshot", "snapshot_item", "transaction",
    name="attachmentsourcetype",
)
SOURCE_NEW = sa.Enum(
    "asset", "movement", "distribution", "snapshot", "snapshot_item", "transaction",
    "account", "credit_card_account",
    name="attachmentsourcetype",
)
HINT_OLD = sa.Enum(
    "BROKER_POSITION", "BROKER_INCOME", "B3_TRADE_NOTE",
    "FGTS_BALANCE", "SCREENSHOT_PRICE", "GENERIC",
    name="extractionsourcehint",
)
HINT_NEW = sa.Enum(
    "BROKER_POSITION", "BROKER_INCOME", "B3_TRADE_NOTE",
    "FGTS_BALANCE", "SCREENSHOT_PRICE", "GENERIC",
    "BANK_STATEMENT", "CARD_INVOICE",
    name="extractionsourcehint",
)

# Mesmo ROOT de services/attachment_storage.py (relativo ao cwd do processo
# — o deploy roda o alembic do mesmo diretório que o app).
ATTACHMENTS_ROOT = Path(os.environ.get("NUMIS_ATTACHMENTS_ROOT", "./data/attachments"))


def _backfill_content_hash() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, storage_key FROM attachment WHERE content_hash IS NULL"
    )).fetchall()
    root = ATTACHMENTS_ROOT.resolve()
    hashed = missing = 0
    for att_id, storage_key in rows:
        try:
            path = (root / storage_key).resolve()
            path.relative_to(root)  # nunca sai da raiz
            blob = path.read_bytes()
        except (OSError, ValueError):
            missing += 1
            continue
        bind.execute(
            sa.text("UPDATE attachment SET content_hash = :h WHERE id = :id"),
            {"h": hashlib.sha256(blob).hexdigest(), "id": att_id},
        )
        hashed += 1
    print(f"[spec71] attachment.content_hash backfill: {hashed} hashed, {missing} sem arquivo")


def upgrade() -> None:
    with op.batch_alter_table("attachment") as batch:
        batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch.alter_column(
            "source_type", existing_type=SOURCE_OLD, type_=SOURCE_NEW, existing_nullable=False,
        )
    op.create_index("ix_attachment_ws_hash", "attachment", ["workspace_id", "content_hash"])
    _backfill_content_hash()

    with op.batch_alter_table("extraction_job") as batch:
        batch.add_column(sa.Column("checking_account_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("credit_card_account_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("statement_period_start", sa.Date(), nullable=True))
        batch.add_column(sa.Column("statement_period_end", sa.Date(), nullable=True))
        batch.create_foreign_key(
            "fk_extraction_job_checking_account", "account", ["checking_account_id"], ["id"],
        )
        batch.create_foreign_key(
            "fk_extraction_job_credit_card_account", "credit_card_account", ["credit_card_account_id"], ["id"],
        )
        batch.alter_column(
            "source_hint", existing_type=HINT_OLD, type_=HINT_NEW, existing_nullable=False,
        )
        batch.alter_column(
            "detected_hint", existing_type=HINT_OLD, type_=HINT_NEW, existing_nullable=True,
        )
    op.create_index("ix_extraction_checking", "extraction_job", ["checking_account_id"])
    op.create_index("ix_extraction_card", "extraction_job", ["credit_card_account_id"])

    with op.batch_alter_table("transaction") as batch:
        batch.add_column(sa.Column("extraction_job_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_transaction_extraction_job", "extraction_job", ["extraction_job_id"], ["id"],
        )
        batch.alter_column(
            "fingerprint", existing_type=sa.String(length=40), type_=sa.String(length=48),
            existing_nullable=False,
        )
    op.create_index("ix_transaction_extraction_job", "transaction", ["extraction_job_id"])


def downgrade() -> None:
    op.drop_index("ix_transaction_extraction_job", table_name="transaction")
    with op.batch_alter_table("transaction") as batch:
        batch.drop_constraint("fk_transaction_extraction_job", type_="foreignkey")
        batch.drop_column("extraction_job_id")
        batch.alter_column(
            "fingerprint", existing_type=sa.String(length=48), type_=sa.String(length=40),
            existing_nullable=False,
        )

    op.drop_index("ix_extraction_card", table_name="extraction_job")
    op.drop_index("ix_extraction_checking", table_name="extraction_job")
    with op.batch_alter_table("extraction_job") as batch:
        batch.alter_column(
            "detected_hint", existing_type=HINT_NEW, type_=HINT_OLD, existing_nullable=True,
        )
        batch.alter_column(
            "source_hint", existing_type=HINT_NEW, type_=HINT_OLD, existing_nullable=False,
        )
        batch.drop_constraint("fk_extraction_job_credit_card_account", type_="foreignkey")
        batch.drop_constraint("fk_extraction_job_checking_account", type_="foreignkey")
        batch.drop_column("statement_period_end")
        batch.drop_column("statement_period_start")
        batch.drop_column("credit_card_account_id")
        batch.drop_column("checking_account_id")

    op.drop_index("ix_attachment_ws_hash", table_name="attachment")
    with op.batch_alter_table("attachment") as batch:
        batch.alter_column(
            "source_type", existing_type=SOURCE_NEW, type_=SOURCE_OLD, existing_nullable=False,
        )
        batch.drop_column("content_hash")
