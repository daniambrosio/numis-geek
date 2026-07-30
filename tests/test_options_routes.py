"""Spec 17/36 — Options HTTP routes.

Cobre parser, create, exercise, expire e auto-settle via TestClient +
override do get_db, além de autorização básica.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.api.app import app
from numis_geek.api.deps import get_db
from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401 — registra tabelas no metadata
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, OptionType
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService


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


def _mk_ws(db, name: str) -> dict:
    """Cria um workspace + FI + conta investment BRL + admin/member."""
    now = datetime.now(timezone.utc)
    ws = WorkspaceService(db).create(name)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP",
        logo_slug="xp", is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="XP Inv",
        account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(acc)
    itub = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Itaú PN", ticker="ITUB4",
        currency=Currency.BRL, current_price=Decimal("33.42"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(itub)
    return {"ws": ws, "acc": acc, "underlying": itub, "now": now}


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws_a = _mk_ws(db, "Opt WS A")
    ws_b = _mk_ws(db, "Opt WS B")
    UserService(db).create(
        ws_a["ws"].id, "opt_admin_a@test.com", "pw", UserRole.admin,
    )
    UserService(db).create(
        ws_a["ws"].id, "opt_member_a@test.com", "pw", UserRole.member,
    )
    UserService(db).create(
        ws_b["ws"].id, "opt_admin_b@test.com", "pw", UserRole.admin,
    )
    # Sysadmin puro (workspace_id=None).
    import bcrypt
    from numis_geek.models.user import User
    now = datetime.now(timezone.utc)
    sys_u = User(
        id=str(uuid.uuid4()), workspace_id=None,
        email="opt_sys@test.internal", name="Sys",
        password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(sys_u)
    db.commit()

    out = {
        "ws_a_id": ws_a["ws"].id,
        "ws_b_id": ws_b["ws"].id,
        "acc_a_id": ws_a["acc"].id,
        "acc_b_id": ws_b["acc"].id,
        "underlying_a_id": ws_a["underlying"].id,
        "underlying_b_id": ws_b["underlying"].id,
        "admin_a": AuthService(db).login("opt_admin_a@test.com", "pw"),
        "member_a": AuthService(db).login("opt_member_a@test.com", "pw"),
        "admin_b": AuthService(db).login("opt_admin_b@test.com", "pw"),
        "sysadmin": AuthService(db).login("opt_sys@test.internal", "pw"),
    }
    db.close()
    return out


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ── /options/parse ──────────────────────────────────────────────────────────


def test_parse_itubr364_put(client):
    r = client.get("/api/options/parse", params={"ticker": "ITUBR364"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prefix"] == "ITUB"
    assert body["month"] == 6  # R = Jun PUT
    assert body["option_type"] == OptionType.PUT.value
    # 364 → 36.40
    assert Decimal(str(body["strike_suggested"])) == Decimal("36.4")


def test_parse_itubf475_call(client):
    r = client.get("/api/options/parse", params={"ticker": "ITUBF475"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["option_type"] == OptionType.CALL.value
    assert body["month"] == 6  # F = Jun CALL
    assert Decimal(str(body["strike_suggested"])) == Decimal("47.5")


def test_parse_invalid_returns_400(client):
    r = client.get("/api/options/parse", params={"ticker": "TOTALLYBAD"})
    assert r.status_code == 400


# ── POST /options ───────────────────────────────────────────────────────────


def _create_option_payload(seed, *, ticker: str, opt_type: str,
                            strike: str, movement_type: str = "SELL_OPEN",
                            movement_date: str = "2026-05-02",
                            quantity: str = "1000",
                            price: str = "0.09") -> dict:
    return {
        "ticker": ticker,
        "underlying_id": seed["underlying_a_id"],
        "account_id": seed["acc_a_id"],
        "option_type": opt_type,
        "strike_price": strike,
        "expiration_date": "2026-06-19",
        "contract_size": 100,
        "movement_type": movement_type,
        "movement_date": movement_date,
        "quantity": quantity,
        "price_per_share": price,
    }


def test_create_option_admin_success(client, seed):
    payload = _create_option_payload(
        seed, ticker="ITUBR364", opt_type="PUT", strike="36.40",
    )
    r = client.post("/api/options", json=payload, headers=_h(seed["admin_a"]))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["option_type"] == "PUT"
    assert Decimal(str(body["strike_price"])) == Decimal("36.4")
    assert body["is_active"] is True
    assert body["underlying_id"] == seed["underlying_a_id"]
    assert body["workspace_id"] == seed["ws_a_id"]
    assert body["underlying_ticker"] == "ITUB4"


def test_create_option_requires_auth(client, seed):
    payload = _create_option_payload(
        seed, ticker="ITUBR365", opt_type="PUT", strike="36.50",
    )
    r = client.post("/api/options", json=payload)  # sem header
    # HTTPBearer(auto_error=True) devolve 403 Not authenticated no missing
    # header; a stack (get_current_user tratando AuthError) devolve 401.
    assert r.status_code in (401, 403)


def test_create_option_cross_workspace_rejected(client, seed):
    """admin_b tenta usar underlying/account do workspace A → 400."""
    payload = _create_option_payload(
        seed, ticker="ITUBR366", opt_type="PUT", strike="36.60",
    )
    r = client.post("/api/options", json=payload, headers=_h(seed["admin_b"]))
    assert r.status_code == 400, r.text
    assert "workspace" in r.json()["detail"].lower()


# ── POST /options/{id}/exercise ─────────────────────────────────────────────


def _create_option_and_return_id(client, seed, **overrides) -> str:
    payload = _create_option_payload(seed, **overrides)
    r = client.post("/api/options", json=payload, headers=_h(seed["admin_a"]))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_exercise_put_generates_buy_on_underlying(client, seed):
    oid = _create_option_and_return_id(
        client, seed, ticker="ITUBR367", opt_type="PUT", strike="36.40",
        quantity="1000", price="0.09",
    )
    r = client.post(
        f"/api/options/{oid}/exercise",
        json={"exercise_date": "2026-06-19"},
        headers=_h(seed["admin_a"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_active"] is False  # closed
    # Verificação direta: BUY em ITUB4 (underlying_a) foi criado
    db = TestSession()
    try:
        buys = db.query(AssetMovement).filter(
            AssetMovement.asset_id == seed["underlying_a_id"],
            AssetMovement.type == AssetMovementType.BUY,
        ).all()
        # PUT sold → BUY at strike−premium = 36.40−0.09 = 36.31
        this_exercise_buy = [b for b in buys if b.unit_price == Decimal("36.31")]
        assert len(this_exercise_buy) >= 1
        assert this_exercise_buy[0].quantity == Decimal("1000")
    finally:
        db.close()


def test_exercise_call_generates_sell_on_underlying(client, seed):
    oid = _create_option_and_return_id(
        client, seed, ticker="ITUBF475", opt_type="CALL", strike="47.50",
        quantity="1000", price="0.34",
    )
    r = client.post(
        f"/api/options/{oid}/exercise",
        json={"exercise_date": "2026-06-19"},
        headers=_h(seed["admin_a"]),
    )
    assert r.status_code == 200, r.text
    db = TestSession()
    try:
        sells = db.query(AssetMovement).filter(
            AssetMovement.asset_id == seed["underlying_a_id"],
            AssetMovement.type == AssetMovementType.SELL,
        ).all()
        # CALL sold → SELL at strike+premium = 47.50+0.34 = 47.84
        this_sell = [s for s in sells if s.unit_price == Decimal("47.84")]
        assert len(this_sell) >= 1
        assert this_sell[0].quantity == Decimal("1000")
    finally:
        db.close()


def test_exercise_cross_workspace_returns_404(client, seed):
    oid = _create_option_and_return_id(
        client, seed, ticker="ITUBR368", opt_type="PUT", strike="36.80",
    )
    r = client.post(
        f"/api/options/{oid}/exercise",
        json={"exercise_date": "2026-06-19"},
        headers=_h(seed["admin_b"]),
    )
    assert r.status_code == 404


# ── POST /options/{id}/expire ───────────────────────────────────────────────


def test_expire_marks_option_inactive(client, seed):
    oid = _create_option_and_return_id(
        client, seed, ticker="ITUBF476", opt_type="CALL", strike="47.60",
        quantity="500", price="0.20",
    )
    r = client.post(
        f"/api/options/{oid}/expire",
        json={"expiration_date": "2026-06-19"},
        headers=_h(seed["admin_a"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False


def test_expire_member_allowed(client, seed):
    """Member do próprio workspace pode fechar opção do ws."""
    oid = _create_option_and_return_id(
        client, seed, ticker="ITUBF477", opt_type="CALL", strike="47.70",
        quantity="100", price="0.20",
    )
    r = client.post(
        f"/api/options/{oid}/expire",
        json={"expiration_date": "2026-06-19"},
        headers=_h(seed["member_a"]),
    )
    assert r.status_code == 200, r.text


# ── POST /options/auto-settle ───────────────────────────────────────────────


def _stub_hp(monkeypatch, price: Decimal):
    """Faz fetch_price_on devolver `price` na data pedida."""
    from numis_geek.services import option_lifecycle as ol
    from numis_geek.services.historical_price import HistoricalPrice

    def _fake(_db, _asset, target):
        return HistoricalPrice(price=price, source="stub", effective_date=target)

    monkeypatch.setattr(ol, "fetch_price_on", _fake)


def test_auto_settle_admin_processes_expired(client, seed, monkeypatch):
    """Cria uma PUT vencida ITM (underlying < strike) e roda auto-settle
    como admin_a; espera 1 exercised no scope do workspace A."""
    # Cria opção via HTTP no admin_a (expira 2026-06-19)
    oid = _create_option_and_return_id(
        client, seed, ticker="ITUBR369", opt_type="PUT", strike="36.40",
        quantity="500", price="0.10",
    )
    _stub_hp(monkeypatch, Decimal("30.00"))  # ITM pra PUT strike 36.40
    r = client.post(
        "/api/options/auto-settle",
        headers=_h(seed["admin_a"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # A resposta agrega TODO workspace A vencido — só validamos que a nossa
    # foi exercised e que o count total bate com a soma dos decisions.
    assert body["exercised"] + body["expired"] + body["skipped"] == len(body["results"])
    ours = [row for row in body["results"] if row["option_id"] == oid]
    assert len(ours) == 1
    assert ours[0]["decision"] == "exercised"


def test_auto_settle_member_forbidden(client, seed):
    r = client.post("/api/options/auto-settle", headers=_h(seed["member_a"]))
    assert r.status_code == 403


def test_auto_settle_requires_auth(client):
    r = client.post("/api/options/auto-settle")
    assert r.status_code in (401, 403)  # HTTPBearer bloqueia
