"""Spec 30 — GET /distributions/chart endpoint."""
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
from numis_geek.models.asset import Asset, AssetClass, OptionType
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.auth import AuthService


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
    ws = Workspace(id=str(uuid.uuid4()), name="Chart WS")
    ws_other = Workspace(id=str(uuid.uuid4()), name="Other WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        country="BR", is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="XP", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    petr = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="Petrobras", ticker="PETR4",
        currency=Currency.BRL, is_active=True, created_at=now, updated_at=now,
    )
    petr_put = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.OPTION, country="BR", name="PETR4 PUT",
        ticker="PETRR300", currency=Currency.BRL,
        underlying_id=petr.id, option_type=OptionType.PUT,
        strike_price=Decimal("30"), expiration_date=date(2026, 6, 19),
        contract_size=100,
        is_active=True, created_at=now, updated_at=now,
    )
    member = User(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        email="chart_member@test.com", name="M",
        password_hash=bcrypt.hashpw(b"memberpass", bcrypt.gensalt()).decode(),
        role=UserRole.member, is_active=True, created_at=now, updated_at=now,
    )
    sysadmin = User(
        id=str(uuid.uuid4()), workspace_id=None,
        email="chart_sa@test.com", name="SA",
        password_hash=bcrypt.hashpw(b"sapass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin, is_active=True, created_at=now, updated_at=now,
    )

    db.add_all([ws, ws_other, fi, acc, petr, petr_put, member, sysadmin])
    db.commit()

    # Distribution: PETR4 dividend in current month
    today = date.today()
    db.add(Distribution(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, asset_id=petr.id,
        type=DistributionType.DIVIDEND, event_date=today,
        gross_amount=Decimal("100"), net_amount=Decimal("100"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=petr_put.id,
        type=AssetMovementType.SELL_OPEN, event_date=today,
        quantity=Decimal("100"), unit_price=Decimal("1.50"),
        gross_amount=Decimal("150"), fee=Decimal("0"),
        net_amount=Decimal("150"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    # PTAX so BRL→USD path works. The chart resolves PTAX by end-of-month
    # with a 15-day walkback, so seed BOTH the distribution date and a date
    # close to end-of-month to cover both lookup paths.
    db.add(PTAXRate(
        id=str(uuid.uuid4()), date=today, rate=Decimal("5.0"),
        source="BCB_SGS", fetched_at=now,
    ))
    from datetime import timedelta
    if today.month == 12:
        last_day = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(today.year, today.month + 1, 1) - timedelta(days=1)
    if last_day != today:
        db.add(PTAXRate(
            id=str(uuid.uuid4()), date=last_day, rate=Decimal("5.0"),
            source="BCB_SGS", fetched_at=now,
        ))
    db.commit()

    tok = AuthService(db).login("chart_member@test.com", "memberpass")
    sa_tok = AuthService(db).login("chart_sa@test.com", "sapass")
    ws_id, ws_other_id = ws.id, ws_other.id
    db.close()
    return {"tok": tok, "sa_tok": sa_tok, "ws_id": ws_id, "ws_other_id": ws_other_id}


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_chart_defaults_return_200(client, seed):
    r = client.get("/api/distributions/chart", headers=auth(seed["tok"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "BRL"
    assert len(body["rows"]) == 12  # default 12m
    assert "totals" in body
    assert "legend" in body


def test_chart_period_24m_returns_24_rows(client, seed):
    r = client.get("/api/distributions/chart?period=24m", headers=auth(seed["tok"]))
    assert r.status_code == 200
    assert len(r.json()["rows"]) == 24


def test_chart_breakdown_type_lists_all_5_legend_keys(client, seed):
    r = client.get(
        "/api/distributions/chart?breakdown=type", headers=auth(seed["tok"]),
    )
    assert r.status_code == 200
    legend_keys = [s["key"] for s in r.json()["legend"]]
    assert legend_keys == ["DIVIDEND", "INTEREST", "JCP", "SECURITIES_LENDING", "OPTION_PREMIUM"]


def test_chart_synthetic_off_drops_option_premium_rows(client, seed):
    r = client.get(
        "/api/distributions/chart?breakdown=type&include_synthetic=false",
        headers=auth(seed["tok"]),
    )
    assert r.status_code == 200
    body = r.json()
    # Legend still has all 5 keys (UI gates the chip)
    assert "OPTION_PREMIUM" in [s["key"] for s in body["legend"]]
    # But no row segment has OPTION_PREMIUM
    for row in body["rows"]:
        assert all(s["key"] != "OPTION_PREMIUM" for s in row["segments"])


def test_chart_currency_usd_converts(client, seed):
    r = client.get(
        "/api/distributions/chart?currency=USD&breakdown=total",
        headers=auth(seed["tok"]),
    )
    assert r.status_code == 200
    # Has at least one row with a total > 0 (current month: 100 BRL + 150 BRL → /5 = 50 USD)
    non_zero = [r for r in r.json()["rows"] if r["total"] > 0]
    assert non_zero, "Expected at least one non-zero bucket"


def test_chart_member_cross_workspace_forbidden(client, seed):
    r = client.get(
        f"/api/distributions/chart?workspace_id={seed['ws_other_id']}",
        headers=auth(seed["tok"]),
    )
    assert r.status_code == 403


def test_chart_sysadmin_cross_workspace_ok(client, seed):
    r = client.get(
        f"/api/distributions/chart?workspace_id={seed['ws_id']}",
        headers=auth(seed["sa_tok"]),
    )
    assert r.status_code == 200


def test_chart_invalid_period_422(client, seed):
    r = client.get("/api/distributions/chart?period=99m", headers=auth(seed["tok"]))
    assert r.status_code == 422


def test_chart_invalid_breakdown_422(client, seed):
    r = client.get("/api/distributions/chart?breakdown=xyz", headers=auth(seed["tok"]))
    assert r.status_code == 422
