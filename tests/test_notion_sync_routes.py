"""Tests for /notion-sync routes (per-entity push, bulk, resolve)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.api.app import app
from numis_geek.api.deps import get_db
from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.integrations.notion import NotionPage
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.models.notion_sync import NotionSyncStatus
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.auth import AuthService
from numis_geek.services.notion_sync import SyncResult

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


def override_get_db():
    db = TestSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="NS WS")
    admin = User(
        id=str(uuid.uuid4()), workspace_id=ws.id, email="ns_admin@test.com",
        name="A", password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=UserRole.admin, is_active=True, created_at=now, updated_at=now,
    )
    sysadmin = User(
        id=str(uuid.uuid4()), workspace_id=None, email="ns_sys@test.internal",
        name="S", password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin, is_active=True, created_at=now, updated_at=now,
    )
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
        asset_class=AssetClass.STOCK, country="BR", name="PETR4", ticker="PETR4",
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
    db.add_all([ws, admin, sysadmin, fi, acc, asset, m])
    for key in [
        "NOTION_TOKEN", "DB_IG_ATIVOS", "DB_IG_LANCAMENTO",
        "DB_IG_APURACAO", "DB_IG_LOTE_APURACAO", "DB_IG_EVENTOS",
    ]:
        db.add(IntegrationCredential(
            id=str(uuid.uuid4()), workspace_id=None,
            provider=IntegrationProvider.NOTION, key_name=key,
            secret_value=f"fake-{key}", is_active=True,
            created_at=now, updated_at=now,
        ))
    db.commit()
    asset_id, movement_id, ws_id = asset.id, m.id, ws.id
    admin_tok = AuthService(db).login("ns_admin@test.com", "pw")
    sys_tok = AuthService(db).login("ns_sys@test.internal", "pw")
    db.close()
    return {
        "admin_tok": admin_tok, "sys_tok": sys_tok,
        "asset_id": asset_id, "movement_id": movement_id, "ws_id": ws_id,
    }


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _mock_synced(page_id="page-1"):
    return SyncResult(
        status=NotionSyncStatus.SYNCED,
        notion_page_id=page_id, notion_url=f"https://notion.so/{page_id}",
        error=None,
    )


def test_pending_counts(client, seed):
    r = client.get("/notion-sync/pending", headers=auth(seed["admin_tok"]))
    assert r.status_code == 200
    body = r.json()
    assert body["assets"] >= 1
    assert body["asset_movements"] >= 1


def test_push_asset_calls_service(client, seed):
    with patch("numis_geek.api.routes.notion_sync.push_asset", return_value=_mock_synced("page-A")) as p:
        r = client.post(
            f"/notion-sync/asset/{seed['asset_id']}",
            headers=auth(seed["admin_tok"]),
        )
    assert r.status_code == 200
    assert r.json()["status"] == "SYNCED"
    assert r.json()["notion_page_id"] == "page-A"
    p.assert_called_once()


def test_push_movement_route(client, seed):
    with patch(
        "numis_geek.api.routes.notion_sync.push_asset_movement",
        return_value=_mock_synced("page-M"),
    ) as p:
        r = client.post(
            f"/notion-sync/asset-movement/{seed['movement_id']}",
            headers=auth(seed["admin_tok"]),
        )
    assert r.status_code == 200
    assert r.json()["notion_page_id"] == "page-M"
    p.assert_called_once()


def test_push_unknown_id_returns_404(client, seed):
    r = client.post(
        "/notion-sync/asset/does-not-exist",
        headers=auth(seed["admin_tok"]),
    )
    assert r.status_code == 404


def test_resolve_force_push(client, seed):
    with patch(
        "numis_geek.api.routes.notion_sync.push_asset",
        return_value=_mock_synced("page-A"),
    ) as p:
        r = client.post(
            f"/notion-sync/asset/{seed['asset_id']}/resolve?action=force_push",
            headers=auth(seed["admin_tok"]),
        )
    assert r.status_code == 200
    p.assert_called_once()
    # force=True was passed
    assert p.call_args.kwargs.get("force") is True


def test_resolve_abort_clears_conflict(client, seed):
    # Manually set status=CONFLICT
    db = TestSession()
    a = db.get(Asset, seed["asset_id"])
    a.notion_sync_status = NotionSyncStatus.CONFLICT
    a.notion_sync_error = "test conflict"
    db.commit()
    db.close()

    r = client.post(
        f"/notion-sync/asset/{seed['asset_id']}/resolve?action=abort",
        headers=auth(seed["admin_tok"]),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "PENDING"

    db = TestSession()
    a = db.get(Asset, seed["asset_id"])
    assert a.notion_sync_status == NotionSyncStatus.PENDING
    assert a.notion_sync_error is None
    db.close()


def test_bulk_assets_only_pending(client, seed):
    # Reset asset to PENDING
    db = TestSession()
    a = db.get(Asset, seed["asset_id"])
    a.notion_sync_status = NotionSyncStatus.PENDING
    db.commit()
    db.close()

    with patch(
        "numis_geek.api.routes.notion_sync.push_asset",
        return_value=_mock_synced("page-A"),
    ) as p:
        r = client.post("/notion-sync/asset/bulk", headers=auth(seed["admin_tok"]))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert body["synced"] >= 1
    p.assert_called()
