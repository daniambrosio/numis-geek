"""Seed Notion credentials (token + DB IDs) into IntegrationCredential.

Idempotent: updates existing rows by (provider, key_name); inserts when missing.
Run via:  uv run python -m scripts.seed_notion_credentials
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from numis_geek.models.integration_credential import (
    IntegrationCredential,
    IntegrationProvider,
)


CREDENTIALS = {
    "NOTION_TOKEN": "ntn_v21373787248YvMuAGKRfJdUDjtkPKQCshTJxsyRrD47Q1",
    "DB_IG_ATIVOS": "18007f65-cfa4-801e-aab6-ccd0a48a56a1",
    "DB_IG_LANCAMENTO": "18007f65-cfa4-80b4-bea7-d5fc771af983",
    "DB_IG_APURACAO": "18007f65-cfa4-80cb-8b25-ff9a9515e27b",
    "DB_IG_LOTE_APURACAO": "19207f65-cfa4-809c-bc31-c842878ee14b",
    "DB_IG_EVENTOS": "18007f65-cfa4-801c-ae7f-e56e081d35b1",
    "DB_IG_PROVENTOS": "18e07f65-cfa4-808e-8c7f-c9a5c5b88849",
}


def main() -> int:
    url = os.environ.get("DATABASE_URL", "sqlite:///numis_geek.db")
    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    db = Session()
    now = datetime.now(timezone.utc)

    for key, value in CREDENTIALS.items():
        existing = (
            db.query(IntegrationCredential)
            .filter(
                IntegrationCredential.provider == IntegrationProvider.NOTION,
                IntegrationCredential.key_name == key,
                IntegrationCredential.workspace_id.is_(None),
            )
            .first()
        )
        if existing:
            existing.secret_value = value
            existing.is_active = True
            existing.updated_at = now
            print(f"updated {key}")
        else:
            db.add(IntegrationCredential(
                id=str(uuid.uuid4()),
                workspace_id=None,
                provider=IntegrationProvider.NOTION,
                key_name=key,
                secret_value=value,
                is_active=True,
                created_at=now,
                updated_at=now,
            ))
            print(f"inserted {key}")
    db.commit()
    db.close()
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
