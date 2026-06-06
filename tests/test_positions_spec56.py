"""Spec 56 — Position FX correctness for BRL assets.

Regression: BRL movements/distributions já trazem valores em BRL no payload.
O `fx_rate` (PTAX) é armazenado pelo design multi-moeda pra permitir exibir
em USD depois — mas NÃO pode ser multiplicado na conversão BRL→BRL. Bug
real visto em prod: PETR4 avg_cost_brl=R$115 quando deveria ser R$25.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.workspace import Workspace
from numis_geek.services.positions import compute_position


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
def db_session():
    s = TestSession()
    yield s
    s.rollback()
    s.close()


def _seed(db, *, asset_class: AssetClass, ccy: Currency, account_ccy: Currency):
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="WS56")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="acc", account_type=AccountType.investment, currency=account_ccy,
        is_active=True, created_at=now, updated_at=now,
    )
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=asset_class, country="BR" if ccy == Currency.BRL else "US",
        name=f"asset-{asset_class.value}", ticker="T56",
        currency=ccy, is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc, asset])
    db.flush()
    return ws, asset, now


# ── Cotado BRL: avg_cost_brl NÃO infla com fx_rate ──────────────────────────


def test_brl_cotado_basis_does_not_multiply_fx(db_session):
    """Antes do fix: BUY de 100 PETR4 @ R$30 com fx=5.4 →
    basis_cost_brl=16200 → avg_cost_brl=R$162.
    Depois do fix: avg_cost_brl=R$30 (igual ao native)."""
    ws, asset, now = _seed(
        db_session, asset_class=AssetClass.STOCK,
        ccy=Currency.BRL, account_ccy=Currency.BRL,
    )
    db_session.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 10),
        quantity=Decimal("100"), unit_price=Decimal("30.00"),
        gross_amount=Decimal("3000.00"), net_amount=Decimal("3000.00"),
        currency=Currency.BRL, fx_rate=Decimal("5.4"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db_session.flush()

    pos = compute_position(db_session, asset.id)
    assert pos["currency"] == "BRL"
    assert pos["quantity_held"] == Decimal("100")
    assert pos["average_cost"] == Decimal("30")
    # CRÍTICO: avg_cost_brl == 30 (não 162 = 30 * 5.4)
    assert pos["average_cost_brl"] == Decimal("30")
    # total_invested_brl = 100 * 30 = 3000 (não 16200)
    assert pos["total_invested_brl"] == Decimal("3000")


def test_brl_non_cotado_total_invested_uses_gross_not_gross_times_fx(db_session):
    """BUY non-cotado (qty=NULL, gross=50000) com fx=5.4 →
    Antes: total_invested_brl = 270000.
    Depois: total_invested_brl = 50000."""
    ws, asset, now = _seed(
        db_session, asset_class=AssetClass.PRIVATE_PENSION,
        ccy=Currency.BRL, account_ccy=Currency.BRL,
    )
    db_session.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset.id,
        type=AssetMovementType.BUY, event_date=date(2025, 11, 25),
        quantity=None, unit_price=None,
        gross_amount=Decimal("50000.00"), net_amount=Decimal("50000.00"),
        currency=Currency.BRL, fx_rate=Decimal("5.3794"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db_session.flush()

    pos = compute_position(db_session, asset.id)
    assert pos["quantity_held"] == Decimal("0")
    # CRÍTICO: 50000, não 268970
    assert pos["total_invested_brl"] == Decimal("50000")


# ── USD: regressão garantindo que conversão USD→BRL continua via fx ─────────


def test_usd_cotado_still_multiplies_fx(db_session):
    """USD asset, BUY de 10 AAPL @ $200 com fx=5.4 →
    avg_cost_brl = 200 * 5.4 = 1080. Fix do Spec 56 só pula fx pra BRL."""
    ws, asset, now = _seed(
        db_session, asset_class=AssetClass.STOCK,
        ccy=Currency.USD, account_ccy=Currency.USD,
    )
    db_session.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset.id,
        type=AssetMovementType.BUY, event_date=date(2026, 3, 15),
        quantity=Decimal("10"), unit_price=Decimal("200.00"),
        gross_amount=Decimal("2000.00"), net_amount=Decimal("2000.00"),
        currency=Currency.USD, fx_rate=Decimal("5.4"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db_session.flush()

    pos = compute_position(db_session, asset.id)
    assert pos["currency"] == "USD"
    assert pos["average_cost"] == Decimal("200")
    assert pos["average_cost_brl"] == Decimal("1080")
    assert pos["total_invested_brl"] == Decimal("10800")  # 10 * 200 * 5.4


# ── Distribution loop em compute_position ───────────────────────────────────


def test_brl_distribution_total_received_ignores_spurious_fx(db_session):
    """Defesa: se algum import futuro fillar PTAX num dividendo BRL, o
    cálculo NÃO deve inflar total_received_brl. Hoje rodando saudável
    porque Notion sync filtra; o test trava o invariante."""
    ws, asset, now = _seed(
        db_session, asset_class=AssetClass.STOCK,
        ccy=Currency.BRL, account_ccy=Currency.BRL,
    )
    # BUY pra ter posição
    db_session.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 1),
        quantity=Decimal("100"), unit_price=Decimal("10"),
        gross_amount=Decimal("1000"), net_amount=Decimal("1000"),
        currency=Currency.BRL, fx_rate=Decimal("5.0"),
        is_active=True, created_at=now, updated_at=now,
    ))
    # DIVIDEND BRL com fx_rate espúrio
    # FK no Distribution exige FI — pega o que foi seedado
    fi_row = db_session.query(FinancialInstitution).first()
    db_session.add(Distribution(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset.id,
        financial_institution_id=fi_row.id,
        type=DistributionType.DIVIDEND, event_date=date(2026, 4, 10),
        gross_amount=Decimal("250"), tax=Decimal("0"),
        net_amount=Decimal("250"),
        currency=Currency.BRL, fx_rate=Decimal("5.4"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db_session.flush()

    pos = compute_position(db_session, asset.id)
    # CRÍTICO: 250 BRL, não 1350 (250 * 5.4)
    assert pos["total_received_brl"] == Decimal("250")


def test_usd_distribution_total_received_uses_fx(db_session):
    """Regressão: USD dist com fx=5.0 → 50 USD * 5.0 = 250 BRL."""
    ws, asset, now = _seed(
        db_session, asset_class=AssetClass.STOCK,
        ccy=Currency.USD, account_ccy=Currency.USD,
    )
    db_session.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 1),
        quantity=Decimal("10"), unit_price=Decimal("100"),
        gross_amount=Decimal("1000"), net_amount=Decimal("1000"),
        currency=Currency.USD, fx_rate=Decimal("5.0"),
        is_active=True, created_at=now, updated_at=now,
    ))
    # FK no Distribution exige FI — pega o que foi seedado
    fi_row = db_session.query(FinancialInstitution).first()
    db_session.add(Distribution(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset.id,
        financial_institution_id=fi_row.id,
        type=DistributionType.DIVIDEND, event_date=date(2026, 4, 10),
        gross_amount=Decimal("50"), tax=Decimal("0"),
        net_amount=Decimal("50"),
        currency=Currency.USD, fx_rate=Decimal("5.0"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db_session.flush()

    pos = compute_position(db_session, asset.id)
    assert pos["total_received_brl"] == Decimal("250")
