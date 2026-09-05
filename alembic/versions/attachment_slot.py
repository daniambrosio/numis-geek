"""anexo de fechamento guarda instituição + finalidade (slot)

- `attachment.institution_id` (FK financial_institution, nullable)
- `attachment.purpose` (POSITIONS | INCOME, nullable)

Backfill: anexos de SNAPSHOT recebem o slot do extraction job mais recente
que os referencia (institution_id + source_hint → purpose). Anexos sem job
ficam NULL — eram exatamente os "perdidos" da UI; os 17 de prod foram
classificados à mão em 2026-09-05 (triagem com preview + SQL cirúrgico).
Uploads novos sempre gravam o slot, então não nascem mais órfãos.

Revision ID: attachment_slot
Revises: spec80_checking_bal
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op


revision = "attachment_slot"
down_revision = "spec80_checking_bal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("attachment") as batch:
        batch.add_column(sa.Column("institution_id", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column(
                "purpose",
                sa.Enum("POSITIONS", "INCOME", name="attachmentpurpose"),
                nullable=True,
            )
        )
        batch.create_foreign_key(
            "fk_attachment_institution",
            "financial_institution",
            ["institution_id"],
            ["id"],
        )

    # Backfill a partir do job mais recente por anexo (só jobs com FI).
    op.execute(sa.text("""
        UPDATE attachment
        SET institution_id = (
            SELECT j.institution_id FROM extraction_job j
            WHERE j.attachment_id = attachment.id AND j.institution_id IS NOT NULL
            ORDER BY j.created_at DESC LIMIT 1
        ),
        purpose = (
            SELECT CASE WHEN j.source_hint = 'BROKER_INCOME' THEN 'INCOME' ELSE 'POSITIONS' END
            FROM extraction_job j
            WHERE j.attachment_id = attachment.id AND j.institution_id IS NOT NULL
            ORDER BY j.created_at DESC LIMIT 1
        )
        WHERE source_type = 'SNAPSHOT'
          AND EXISTS (
            SELECT 1 FROM extraction_job j
            WHERE j.attachment_id = attachment.id AND j.institution_id IS NOT NULL
          )
    """))


def downgrade() -> None:
    with op.batch_alter_table("attachment") as batch:
        batch.drop_constraint("fk_attachment_institution", type_="foreignkey")
        batch.drop_column("purpose")
        batch.drop_column("institution_id")
