"""Tests for spec 16 — Notion sync service.

Covers credential loading, conflict detection, idempotency (create →
update via external_id), and the AssetMovement-pushes-Asset-first
dependency. HTTP calls are mocked via monkeypatching the NotionClient
methods.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.integrations.notion import NotionPage
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.corporate_action import CorporateAction, CorporateActionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.models.notion_sync import NotionSyncStatus
from numis_geek.models.workspace import Workspace
from numis_geek.services import notion_sync as svc

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)


@pytest.fixture
def db():
    s = TestSession()
    yield s
    s.rollback()
    s.close()


def _seed_credentials(db):
    now = datetime.now(timezone.utc)
    for key in [
        "NOTION_TOKEN",
        "DB_IG_ATIVOS",
        "DB_IG_LANCAMENTO",
        "DB_IG_APURACAO",
        "DB_IG_LOTE_APURACAO",
        "DB_IG_EVENTOS",
    ]:
        db.add(IntegrationCredential(
            id=str(uuid.uuid4()), workspace_id=None,
            provider=IntegrationProvider.NOTION, key_name=key,
            secret_value=f"fake-{key}", is_active=True,
            created_at=now, updated_at=now,
        ))
    db.flush()


def _seed_world(db):
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="X", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="Petrobras", ticker="PETR4",
        currency=Currency.BRL, is_active=True, created_at=now, updated_at=now,
        notion_sync_status=NotionSyncStatus.PENDING,
    )
    m = AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset.id,
        type=AssetMovementType.BUY, event_date=date(2026, 5, 20),
        quantity=Decimal("100"), unit_price=Decimal("38.50"),
        gross_amount=Decimal("3850"), net_amount=Decimal("3850"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
        notion_sync_status=NotionSyncStatus.PENDING,
    )
    db.add_all([ws, fi, acc, asset, m])
    _seed_credentials(db)
    db.flush()
    return {"ws": ws, "asset": asset, "m": m}


def _mock_client_create(page_id="page-1", edited="2026-05-23T10:00:00.000Z"):
    cli = MagicMock()
    cli.create_page.return_value = NotionPage(
        id=page_id, last_edited_time=edited, properties={}, url=f"https://notion.so/{page_id}"
    )
    cli.update_page.return_value = NotionPage(
        id=page_id, last_edited_time=edited, properties={}, url=f"https://notion.so/{page_id}"
    )
    return cli


def test_push_asset_creates_then_updates_idempotent(db):
    world = _seed_world(db)
    cli = _mock_client_create("asset-page-1")

    r1 = svc.push_asset(db, world["asset"], client=cli)
    assert r1.status == NotionSyncStatus.SYNCED
    assert r1.notion_page_id == "asset-page-1"
    assert world["asset"].external_id == "asset-page-1"
    assert world["asset"].notion_sync_status == NotionSyncStatus.SYNCED
    cli.create_page.assert_called_once()
    cli.update_page.assert_not_called()

    # 2nd push: must UPDATE the existing page
    cli.retrieve_page.return_value = NotionPage(
        id="asset-page-1",
        last_edited_time=world["asset"].notion_remote_last_edited_at.isoformat() + "Z",
        properties={}, url="",
    )
    r2 = svc.push_asset(db, world["asset"], client=cli)
    assert r2.status == NotionSyncStatus.SYNCED
    cli.update_page.assert_called_once()


def test_push_movement_pushes_asset_first(db):
    world = _seed_world(db)
    cli = _mock_client_create("page-A")
    # Each new create_page returns different id sequentially
    cli.create_page.side_effect = [
        NotionPage(id="asset-page", last_edited_time="2026-05-23T10:00:00.000Z", properties={}, url=""),
        NotionPage(id="movement-page", last_edited_time="2026-05-23T10:00:01.000Z", properties={}, url=""),
    ]

    r = svc.push_asset_movement(db, world["m"], client=cli)
    assert r.status == NotionSyncStatus.SYNCED
    assert world["asset"].external_id == "asset-page"
    assert world["m"].external_id == "movement-page"
    assert cli.create_page.call_count == 2


def test_conflict_detection(db):
    world = _seed_world(db)
    asset = world["asset"]
    cli = _mock_client_create("page-1")

    # First push: SYNCED
    svc.push_asset(db, asset, client=cli)
    assert asset.notion_sync_status == NotionSyncStatus.SYNCED

    # Second push: pretend Notion has been edited remotely AFTER our sync
    cli.retrieve_page.return_value = NotionPage(
        id="page-1", last_edited_time="2099-01-01T00:00:00.000Z",
        properties={}, url="",
    )
    r = svc.push_asset(db, asset, client=cli)
    assert r.status == NotionSyncStatus.CONFLICT
    assert asset.notion_sync_status == NotionSyncStatus.CONFLICT
    # update_page must NOT be called when conflict
    cli.update_page.assert_not_called()


def test_force_push_bypasses_conflict(db):
    world = _seed_world(db)
    asset = world["asset"]
    cli = _mock_client_create("page-1")
    svc.push_asset(db, asset, client=cli)

    cli.retrieve_page.return_value = NotionPage(
        id="page-1", last_edited_time="2099-01-01T00:00:00.000Z",
        properties={}, url="",
    )
    r = svc.push_asset(db, asset, client=cli, force=True)
    assert r.status == NotionSyncStatus.SYNCED
    cli.update_page.assert_called_once()


def test_missing_credential_raises(db):
    world = _seed_world(db)
    db.query(IntegrationCredential).filter(
        IntegrationCredential.key_name == "NOTION_TOKEN"
    ).delete()
    db.flush()
    with pytest.raises(svc.NotionCredentialMissing):
        svc.push_asset(db, world["asset"])


def test_corporate_action_asset_conversion_skipped(db):
    world = _seed_world(db)
    now = datetime.now(timezone.utc)
    ca = CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws"].id, asset_id=world["asset"].id,
        event_date=date(2026, 1, 15), event_type=CorporateActionType.ASSET_CONVERSION,
        ratio=Decimal("1"), is_active=True, created_at=now, updated_at=now,
        notion_sync_status=NotionSyncStatus.PENDING,
    )
    db.add(ca)
    db.flush()
    r = svc.push_corporate_action(db, ca)
    assert r.status == NotionSyncStatus.ERROR
    assert "ASSET_CONVERSION" in (r.error or "")


def test_corporate_action_split_creates_page(db):
    world = _seed_world(db)
    cli = _mock_client_create("ca-page")
    cli.create_page.side_effect = [
        NotionPage(id="asset-page", last_edited_time="2026-05-23T10:00:00.000Z", properties={}, url=""),
        NotionPage(id="ca-page", last_edited_time="2026-05-23T10:00:01.000Z", properties={}, url=""),
    ]
    now = datetime.now(timezone.utc)
    ca = CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws"].id, asset_id=world["asset"].id,
        event_date=date(2026, 1, 15), event_type=CorporateActionType.SPLIT,
        ratio=Decimal("10"), is_active=True, created_at=now, updated_at=now,
        notion_sync_status=NotionSyncStatus.PENDING,
    )
    db.add(ca)
    db.flush()
    r = svc.push_corporate_action(db, ca, client=cli)
    assert r.status == NotionSyncStatus.SYNCED
    assert ca.external_id == "ca-page"


def test_list_pending_counts(db):
    world = _seed_world(db)
    counts = svc.list_pending(db, world["ws"].id)
    assert counts["assets"] >= 1
    assert counts["asset_movements"] >= 1
