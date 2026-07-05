"""Regression tests para o fix Fase 2 B1 — variation=None em value mode.

Bug original: PGBL Flexprev com 23 aportes value-mode (post-migration
normalize_valor_qty, cada aporte = qty=1) fazia compute_position
retornar current_value = 23 × current_price (~R$500k) inflando dashboard
+R$ 7-8M. A razão (current_price - avg) / avg dava +2000%+ no Top Movers.

Fix: em value mode, effective_qty=1 (current_value = current_price total)
e variation=None (comparação avg-per-aporte vs current-total é falsa).
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
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.services.positions import compute_position
from numis_geek.services.workspace import WorkspaceService


ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(ENGINE)
    yield
    Base.metadata.drop_all(ENGINE)


@pytest.fixture
def world():
    db = Session()
    ws = WorkspaceService(db).create(f"VM WS {uuid.uuid4().hex[:8]}")
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP",
        logo_slug="xp", is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    account = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="Prev",
        account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(account)
    db.commit()
    yield {"db": db, "ws_id": ws.id, "account_id": account.id, "now": now}
    db.close()


def _add_value_mode_movement(
    db, ws_id, asset_id, gross, event_date, mtype=AssetMovementType.BUY,
):
    """Cria movement no formato pós-normalize_valor_qty: qty=1, unit_price=gross."""
    db.add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        asset_id=asset_id,
        type=mtype,
        event_date=event_date,
        quantity=Decimal("1"),
        unit_price=Decimal(str(gross)),
        gross_amount=Decimal(str(gross)),
        net_amount=Decimal(str(gross)),
        currency=Currency.BRL,
    ))
    db.commit()


def _make_asset(db, ws_id, account_id, asset_class, current_price):
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_id, account_id=account_id,
        asset_class=asset_class, country="BR",
        name=f"Test {asset_class.value}", ticker=None,
        currency=Currency.BRL, is_active=True,
        current_price=Decimal(str(current_price)),
        created_at=now, updated_at=now,
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


def test_variation_is_none_in_value_mode(world):
    """PRIVATE_PENSION com 5 aportes: variation deve ser None."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.PRIVATE_PENSION, current_price=500_000,
    )
    for i in range(5):
        _add_value_mode_movement(
            world["db"], world["ws_id"], a.id,
            gross=20_000, event_date=date(2026, 1, 1 + i),
        )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    # invariante do fix: variation=None em value mode
    assert pos["variation"] is None
    # current_value = 1 × current_price (não N × current_price)
    assert pos["current_value"] == Decimal("500000")
    assert pos["current_value_brl"] == Decimal("500000")
    # sanity: quantity_held reflete os N aportes (running_qty), não zeramos
    assert pos["quantity_held"] == Decimal("5")


def test_variation_calculated_in_cotado_mode(world):
    """STOCK com aportes normais: variation deve ser calculada."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.STOCK, current_price=40,
    )
    now = datetime.now(timezone.utc)
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY,
        event_date=date(2026, 1, 1),
        quantity=Decimal("100"), unit_price=Decimal("30"),
        gross_amount=Decimal("3000"), net_amount=Decimal("3000"),
        currency=Currency.BRL,
    ))
    world["db"].commit()
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    # (40 - 30) / 30 = 0.3333
    assert pos["variation"] is not None
    assert abs(pos["variation"] - Decimal("0.3333333333333333333333333333")) < Decimal("0.001")


def test_regression_23_aportes_does_not_inflate_current_value(world):
    """Bug original: PGBL 23 aportes × R$21k, current_price=R$500k
    (VALOR TOTAL). Pre-fix dava current_value=R$11.5M (23×500k)
    e variation=+2280% no Top Movers.
    """
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.PRIVATE_PENSION, current_price=500_000,
    )
    for i in range(23):
        _add_value_mode_movement(
            world["db"], world["ws_id"], a.id,
            gross=21_000, event_date=date(2024, 1, 1) + (date(2024, 2, 1) - date(2024, 1, 1)) * i,
        )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["current_value"] == Decimal("500000")  # NÃO 23 × 500k
    assert pos["variation"] is None                     # NÃO +2280%
    # rentabilidade ainda calcula corretamente: (500k - 23×21k) / 23×21k = 0.0352
    # (basis vai pro caminho cotado porque qty=1 é preservada — running_qty=23,
    # basis_qty=23, avg_cost_brl=21k, total_invested_brl=23×21k=483k)
    assert pos["total_invested_brl"] == Decimal("483000")
    expected_rent = (Decimal("500000") - Decimal("483000")) / Decimal("483000")
    assert abs(pos["rentabilidade"] - expected_rent) < Decimal("0.001")


def test_fund_class_also_value_mode(world):
    """FUND (fundo de investimento) deve seguir a mesma regra de PREV/FGTS."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=100_000,
    )
    for i in range(3):
        _add_value_mode_movement(
            world["db"], world["ws_id"], a.id,
            gross=30_000, event_date=date(2026, 1, 1 + i),
        )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["variation"] is None
    assert pos["current_value"] == Decimal("100000")


def test_variation_none_when_no_current_price(world):
    """Sanity: sem current_price, todos os derivados são None."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.STOCK, current_price=30,
    )
    a.current_price = None
    world["db"].commit()
    world["db"].refresh(a)
    now = datetime.now(timezone.utc)
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 1),
        quantity=Decimal("10"), unit_price=Decimal("20"),
        gross_amount=Decimal("200"), net_amount=Decimal("200"),
        currency=Currency.BRL,
    ))
    world["db"].commit()
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["current_value"] is None
    assert pos["variation"] is None
    assert pos["rentabilidade"] is None
