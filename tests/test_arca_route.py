"""Spec 85 — rotas ARCA: RBAC, resumo, simulador, classificação, metas."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

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
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotSource,
)
from numis_geek.models.user import User, UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService

ENGINE = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)
NOW = datetime.now(timezone.utc)
D = Decimal


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(ENGINE)
    yield
    Base.metadata.drop_all(ENGINE)


def override_get_db():
    db = Session()
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


def _asset(db, ws_id, acc_id, ticker, cls):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_id, account_id=acc_id, asset_class=cls,
        country="BR", name=ticker, ticker=ticker, currency=Currency.BRL,
        is_active=True, created_at=NOW, updated_at=NOW,
    )
    db.add(a)
    db.flush()
    return a


@pytest.fixture(scope="module")
def seed():
    db = Session()
    ws_a = WorkspaceService(db).create("ARCA-A")
    ws_b = WorkspaceService(db).create("ARCA-B")
    UserService(db).create(ws_a.id, "arca_admin@test.com", "pw", UserRole.admin)
    UserService(db).create(ws_a.id, "arca_member@test.com", "pw", UserRole.member)
    UserService(db).create(ws_b.id, "arca_admin_b@test.com", "pw", UserRole.admin)
    db.add(User(
        id=str(uuid.uuid4()), workspace_id=None, email="arca_sys@test.internal", name="S",
        password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin, is_active=True, created_at=NOW, updated_at=NOW,
    ))
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", country="BR",
        is_active=True, created_at=NOW, updated_at=NOW,
    )
    db.add(fi)
    db.flush()
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws_a.id, financial_institution_id=fi.id,
        name="Inv", account_type=AccountType.investment, currency=Currency.BRL,
        opening_balance=D("0"), is_active=True, created_at=NOW, updated_at=NOW,
    )
    db.add(acc)
    db.flush()
    itub = _asset(db, ws_a.id, acc.id, "ITUB4", AssetClass.STOCK)
    bova = _asset(db, ws_a.id, acc.id, "BOVA11", AssetClass.ETF)
    acc_b = Account(
        id=str(uuid.uuid4()), workspace_id=ws_b.id, financial_institution_id=fi.id,
        name="InvB", account_type=AccountType.investment, currency=Currency.BRL,
        opening_balance=D("0"), is_active=True, created_at=NOW, updated_at=NOW,
    )
    db.add(acc_b)
    db.flush()
    other = _asset(db, ws_b.id, acc_b.id, "PETR4", AssetClass.STOCK)
    s = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws_a.id, period_end_date=date(2026, 10, 31),
        fx_rate_usd_brl=D("5"), total_value_brl=D("100"), total_value_usd=D("20"),
        total_invested_brl=D("0"), total_received_brl=D("0"), source=SnapshotSource.MANUAL,
        is_active=True, created_at=NOW, updated_at=NOW,
    )
    db.add(s)
    db.flush()
    for a, v in ((itub, D("60")), (bova, D("40"))):
        db.add(PortfolioSnapshotItem(
            id=str(uuid.uuid4()), snapshot_id=s.id, asset_id=a.id, quantity=D("1"),
            unit_price=v, market_value_native=v, market_value_brl=v, market_value_usd=v / 5,
        ))
    db.commit()
    out = {
        "ws_a": ws_a.id, "ws_b": ws_b.id, "itub": itub.id, "bova": bova.id, "other": other.id,
        "admin": AuthService(db).login("arca_admin@test.com", "pw"),
        "member": AuthService(db).login("arca_member@test.com", "pw"),
        "admin_b": AuthService(db).login("arca_admin_b@test.com", "pw"),
        "sys": AuthService(db).login("arca_sys@test.internal", "pw"),
    }
    db.close()
    return out


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


EQUAL = [{"key": k, "target_pct": "0.25"} for k in ("EQUITY_BR", "REAL_ESTATE", "CASH", "GLOBAL")]


def test_summary_member_ok_and_cross_ws_forbidden(client, seed):
    r = client.get(f"/api/workspaces/{seed['ws_a']}/arca/summary", headers=H(seed["member"]))
    assert r.status_code == 200
    body = r.json()
    assert body["unmapped_count"] == 1 and D(body["total_brl"]) == D("60")
    assert [l["key"] for l in body["letters"]] == ["EQUITY_BR", "REAL_ESTATE", "CASH", "GLOBAL"]
    r = client.get(f"/api/workspaces/{seed['ws_a']}/arca/summary", headers=H(seed["admin_b"]))
    assert r.status_code == 403
    r = client.get(f"/api/workspaces/{seed['ws_a']}/arca/summary", headers=H(seed["sys"]))
    assert r.status_code == 200


def test_targets_put_arca_admin_only(client, seed):
    url = f"/api/workspaces/{seed['ws_a']}/target-allocation"
    r = client.put(url, json={"dimension": "ARCA", "entries": EQUAL}, headers=H(seed["member"]))
    assert r.status_code == 403
    r = client.put(url, json={"dimension": "ARCA", "entries": EQUAL}, headers=H(seed["admin"]))
    assert r.status_code == 200, r.text
    assert r.json()["ARCA"]["is_valid"] is True
    bad = [{"key": "CASH", "target_pct": "1"}]
    r = client.put(url, json={"dimension": "ARCA", "entries": bad}, headers=H(seed["admin"]))
    assert r.status_code == 400
    subs = [{"key": "CASH_POST_FIXED", "target_pct": "1"}]
    r = client.put(url, json={"dimension": "ARCA_SUB", "entries": subs}, headers=H(seed["admin"]))
    assert r.status_code == 200
    assert r.json()["ARCA_SUB"]["entries"][0]["key"] == "CASH_POST_FIXED"


def test_plan(client, seed):
    url = f"/api/workspaces/{seed['ws_a']}/arca/contribution-plan"
    r = client.post(url, json={"amount_brl": "100"}, headers=H(seed["member"]))
    assert r.status_code == 200, r.text
    total = sum(D(l["amount_brl"]) for l in r.json()["letters"])
    assert total == D("100.00")
    r = client.post(url, json={"amount_brl": "0"}, headers=H(seed["member"]))
    assert r.status_code == 422


def test_classification_put(client, seed):
    url = f"/api/workspaces/{seed['ws_a']}/arca/classification"
    r = client.put(url, json={"items": [
        {"asset_id": seed["bova"], "category": "EQUITY_BR", "subcategory": "EQ_DEFENSIVE"},
    ]}, headers=H(seed["member"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unmapped_count"] == 0
    row = next(a for a in body["assets"] if a["asset_id"] == seed["bova"])
    assert (row["category"], row["subcategory"], row["source"]) == ("EQUITY_BR", "EQ_DEFENSIVE", "manual")
    db = Session()
    assert db.query(AuditLog).filter(AuditLog.action == "asset.arca_classification").count() == 1
    db.close()
    # incompatible
    r = client.put(url, json={"items": [
        {"asset_id": seed["bova"], "category": "CASH", "subcategory": "EQ_DEFENSIVE"},
    ]}, headers=H(seed["member"]))
    assert r.status_code == 422
    # asset of another workspace
    r = client.put(url, json={"items": [{"asset_id": seed["other"], "category": "CASH"}]},
                   headers=H(seed["member"]))
    assert r.status_code == 404
    # reset to automatic
    r = client.put(url, json={"items": [{"asset_id": seed["bova"]}]}, headers=H(seed["member"]))
    assert r.json()["unmapped_count"] == 1
