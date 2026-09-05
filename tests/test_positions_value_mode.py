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
from numis_geek.services.positions import asset_has_position, compute_position
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
    # Spec 78 — quantity_held em modo valor é 0: o antigo "5" era o nº de
    # lançamentos, não posição. A posição é o valor.
    assert pos["quantity_held"] == Decimal("0")
    assert pos["is_value_mode"] is True


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
    # (spec 64: os 23 aportes entram no basis non_cotado — Σ gross = 483k;
    # antes iam pelo caminho cotado com basis_qty=23 e avg 21k, mesmo total)
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


def test_full_redeemed_value_mode_hides_current_value(world):
    """Bug 2026-07-05 audit — FULL_REDEMPTION zerava basis mas
    effective_qty=1 continuava, mostrando current_value = current_price
    pra posição zerada.
    """
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=100_000,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=50_000, event_date=date(2026, 1, 1),
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=50_000, event_date=date(2026, 2, 1),
        mtype=AssetMovementType.FULL_REDEMPTION,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    # posição foi zerada → não mostrar current_value fantasma
    assert pos["current_value"] is None
    assert pos["current_value_brl"] is None
    assert pos["quantity_held"] == Decimal("0")


def test_hybrid_cotado_plus_non_cotado_sums_both(world):
    """Bug 2026-07-05 audit — se um asset tinha BUY cotado (qty>0)
    E BUY non-cotado (qty=None, gross=X), o if/else descartava um lado.
    Tesouro Selic 2031 aparecia com total_invested_brl negativo.
    """
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FIXED_INCOME, current_price=15_000,
    )
    # BUY cotado: 100 títulos @ R$100
    now = datetime.now(timezone.utc)
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 1),
        quantity=Decimal("100"), unit_price=Decimal("100"),
        gross_amount=Decimal("10000"), net_amount=Decimal("10000"),
        currency=Currency.BRL,
    ))
    # BUY non-cotado (qty=None, gross=5000)
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 2, 1),
        quantity=None, unit_price=None,
        gross_amount=Decimal("5000"), net_amount=Decimal("5000"),
        currency=Currency.BRL,
    ))
    world["db"].commit()
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    # 100 × 100 (cotado) + 5000 (non_cotado) = 15000
    assert pos["total_invested_brl"] == Decimal("15000")


def test_value_mode_uses_frozen_snapshot_price_when_available(world):
    """Bug 2026-07-05 audit — value-mode asset com current_price stale
    (Fundo Verde BTG R$1,72) deveria usar market_value_native do último
    snapshot CLOSED (R$81.912) como preço atual.
    """
    from numis_geek.models.portfolio_snapshot import (
        PortfolioSnapshot, PortfolioSnapshotItem, SnapshotStatus,
    )
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=1.72,  # STALE
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=80_000, event_date=date(2025, 1, 1),
    )
    # Snapshot CLOSED mar/26 com mv_native fresh
    now = datetime.now(timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"],
        period_end_date=date(2026, 3, 31),
        fx_rate_usd_brl=Decimal("5.00"),
        total_value_brl=Decimal("81912"),
        total_value_usd=Decimal("16382.40"),
        total_invested_brl=Decimal("80000"),
        status=SnapshotStatus.CLOSED,
        closed_at=now, closed_by="test",
        is_active=True,
        created_at=now, updated_at=now,
    )
    world["db"].add(snap)
    world["db"].add(PortfolioSnapshotItem(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=a.id,
        quantity=Decimal("1"),
        unit_price=Decimal("81912"),
        market_value_native=Decimal("81912"),
        market_value_brl=Decimal("81912"),
        market_value_usd=Decimal("16382.40"),
        total_invested_brl=Decimal("80000"),
        created_at=now, updated_at=now,
    ))
    world["db"].commit()
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    # DEVE usar R$81.912 do snapshot, não R$1,72 do asset.current_price
    assert pos["current_value"] == Decimal("81912")
    assert pos["current_value_brl"] == Decimal("81912")


def test_value_mode_frozen_price_respects_as_of(world):
    """Snapshot fechado APÓS as_of não deve influenciar posição retroativa."""
    from numis_geek.models.portfolio_snapshot import (
        PortfolioSnapshot, PortfolioSnapshotItem, SnapshotStatus,
    )
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=50_000,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=40_000, event_date=date(2025, 1, 1),
    )
    now = datetime.now(timezone.utc)
    # Snapshot fechado jun/26 (após as_of=mar/26)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"],
        period_end_date=date(2026, 6, 30),
        fx_rate_usd_brl=Decimal("5.00"),
        total_value_brl=Decimal("100000"),
        total_value_usd=Decimal("20000"),
        total_invested_brl=Decimal("40000"),
        status=SnapshotStatus.CLOSED,
        closed_at=now, closed_by="test",
        is_active=True,
        created_at=now, updated_at=now,
    )
    world["db"].add(snap)
    world["db"].add(PortfolioSnapshotItem(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=a.id,
        quantity=Decimal("1"),
        unit_price=Decimal("100000"),
        market_value_native=Decimal("100000"),
        market_value_brl=Decimal("100000"),
        market_value_usd=Decimal("20000"),
        total_invested_brl=Decimal("40000"),
        created_at=now, updated_at=now,
    ))
    world["db"].commit()
    # Posição em mar/26 (as_of anterior ao snapshot jun/26)
    pos = compute_position(world["db"], a.id, as_of=date(2026, 3, 31))
    # NÃO deve usar mv_native=100000 do snapshot jun/26 (posterior).
    # Cai no asset.current_price=50000.
    assert pos["current_value"] == Decimal("50000")


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


def test_hybrid_sell_zeroing_cotado_preserves_non_cotado(world):
    """Bug 2026-07-07 audit — reset_basis() em SELL que zerava running_qty
    também zerava non_cotado_basis_brl, perdendo o componente non_cotado
    do total_invested_brl. Fix: SELL usa reset_cotado_basis() (só cotado).

    Spec 64 — o cenário híbrido só existe em classe COTADA: em modo valor
    toda linha com gross entra no basis non_cotado e `reset_cotado_basis`
    nem é alcançado (ver
    `test_value_mode_hybrid_sums_all_gross_without_reset`).
    """
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.STOCK, current_price=15_000,
    )
    now = datetime.now(timezone.utc)
    # BUY cotado: 100 títulos @ R$100
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 1),
        quantity=Decimal("100"), unit_price=Decimal("100"),
        gross_amount=Decimal("10000"), net_amount=Decimal("10000"),
        currency=Currency.BRL,
    ))
    # BUY non-cotado: R$ 5000 saldo em conta
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 2, 1),
        quantity=None, unit_price=None,
        gross_amount=Decimal("5000"), net_amount=Decimal("5000"),
        currency=Currency.BRL,
    ))
    # SELL 100 zerando o cotado (running_qty→0 dispara reset)
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.SELL, event_date=date(2026, 3, 1),
        quantity=Decimal("100"), unit_price=Decimal("110"),
        gross_amount=Decimal("11000"), net_amount=Decimal("11000"),
        currency=Currency.BRL,
    ))
    world["db"].commit()
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    # Cotado zerou (running_qty=0, basis_cost_brl=0). Non_cotado persiste.
    # total_invested_brl = 0 + 5000 = 5000.
    assert pos["total_invested_brl"] == Decimal("5000")
    assert pos["quantity_held"] == Decimal("0")


def test_value_mode_hybrid_sums_all_gross_without_reset(world):
    """Spec 64 — mesmo cenário do teste acima, mas em classe de modo valor
    (FIXED_INCOME): `quantity` é convenção, não tamanho de posição. Todo
    gross entra no basis non_cotado e o SELL apenas subtrai — sem reset.
    """
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FIXED_INCOME, current_price=15_000,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=10_000, event_date=date(2026, 1, 1),
    )
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 2, 1),
        quantity=None, unit_price=None,
        gross_amount=Decimal("5000"), net_amount=Decimal("5000"),
        currency=Currency.BRL,
    ))
    world["db"].commit()
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=11_000, event_date=date(2026, 3, 1),
        mtype=AssetMovementType.SELL,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["total_invested_brl"] == Decimal("4000")


def test_value_mode_partial_sell_keeps_position(world):
    """Spec 64 — caso LFT mar/2028 (XP): BUY R$ 4.838,54 + resgate parcial
    de R$ 522,43, ambos qty=1 (invariante `modo_valor_qty_1`). Antes do fix
    o SELL zerava running_qty, disparava reset_cotado_basis e o ativo sumia
    do fechamento com invested=0.
    """
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FIXED_INCOME, current_price=5_278.74,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross="4838.535", event_date=date(2025, 5, 6),
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross="522.43", event_date=date(2025, 9, 25),
        mtype=AssetMovementType.SELL,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 8, 31))
    # gross_amount é NUMERIC(18,2): 4838.535 → 4838.53 na coluna.
    assert pos["total_invested_brl"] == Decimal("4316.10")
    assert asset_has_position(pos, a) is True


def test_value_mode_only_buys_sums_gross(world):
    """FUND só com aportes: invested = Σ gross."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=25_000,
    )
    for i, g in enumerate((10_000, 7_500, 2_500)):
        _add_value_mode_movement(
            world["db"], world["ws_id"], a.id,
            gross=g, event_date=date(2026, 1, 1 + i),
        )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["total_invested_brl"] == Decimal("20000")


def test_value_mode_multiple_buys_and_sells(world):
    """FUND com aportes e resgates parciais: invested = Σ BUY − Σ SELL."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=25_000,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=10_000, event_date=date(2026, 1, 1),
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=3_000, event_date=date(2026, 2, 1),
        mtype=AssetMovementType.SELL,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=5_000, event_date=date(2026, 3, 1),
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=2_000, event_date=date(2026, 4, 1),
        mtype=AssetMovementType.SELL,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["total_invested_brl"] == Decimal("10000")
    assert asset_has_position(pos, a) is True


def _add_cotado_movement(db, ws_id, asset_id, qty, unit, event_date, mtype):
    db.add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=ws_id, asset_id=asset_id, type=mtype,
        event_date=event_date,
        quantity=Decimal(str(qty)), unit_price=Decimal(str(unit)),
        gross_amount=Decimal(str(qty)) * Decimal(str(unit)),
        net_amount=Decimal(str(qty)) * Decimal(str(unit)),
        currency=Currency.BRL,
    ))
    db.commit()


def test_value_mode_quantity_held_is_always_zero(world):
    """Spec 78 — em modo valor `quantity_held` não expõe o nº de lançamentos.

    Um FUND com 3 aportes e 1 resgate devolvia running_qty=2 ("2 quê?").
    A posição é o valor; quantidade não se aplica.
    """
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=25_000,
    )
    for i, g in enumerate((10_000, 7_500, 5_000)):
        _add_value_mode_movement(
            world["db"], world["ws_id"], a.id,
            gross=g, event_date=date(2026, 1, 1 + i),
        )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=2_500, event_date=date(2026, 2, 1),
        mtype=AssetMovementType.SELL,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["quantity_held"] == Decimal("0")
    assert pos["is_value_mode"] is True
    # a posição continua existindo — pelo valor, não pela quantidade
    assert pos["total_invested_brl"] == Decimal("20000")
    assert asset_has_position(pos, a) is True


def test_value_mode_zero_invested_leaves_the_fechamento(world):
    """Spec 78 — o vazamento que a regra fecha: invested zerado mas nº de
    aportes ≠ nº de resgates mantinha o ativo preso no fechamento pra sempre.
    """
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=0,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=10_000, event_date=date(2026, 1, 1),
    )
    # dois resgates parciais que somam o aporte inteiro → invested 0,
    # running_qty = 1 − 2 = −1
    for i, g in enumerate((6_000, 4_000)):
        _add_value_mode_movement(
            world["db"], world["ws_id"], a.id,
            gross=g, event_date=date(2026, 2, 1 + i),
            mtype=AssetMovementType.SELL,
        )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["total_invested_brl"] == Decimal("0")
    assert pos["quantity_held"] == Decimal("0")
    assert asset_has_position(pos, a) is False
    # e sem posição não sobra current_value fantasma
    assert pos["current_value"] is None


def test_cash_stays_in_the_fechamento_even_with_zero_invested(world):
    """Spec 78 não pode derrubar os 'Saldo em Conta': CASH é saldo digitado
    por fechamento, sem lançamento nenhum."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.CASH, current_price=0,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["total_invested_brl"] == Decimal("0")
    assert asset_has_position(pos, a) is True


def test_cotado_quantity_still_drives_position(world):
    """Spec 78 — sem regressão: em modo cotado a quantidade continua sendo
    posição e continua decidindo presença."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.STOCK, current_price=30,
    )
    _add_cotado_movement(
        world["db"], world["ws_id"], a.id, 10, 25, date(2026, 1, 1),
        AssetMovementType.BUY,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["quantity_held"] == Decimal("10")
    assert pos["is_value_mode"] is False
    assert asset_has_position(pos, a) is True


def test_cotado_sell_all_still_closes_position(world):
    """Spec 64 — sem regressão em cotado: STOCK BUY 10 + SELL 10 zera."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.STOCK, current_price=30,
    )
    _add_cotado_movement(
        world["db"], world["ws_id"], a.id, 10, 25, date(2026, 1, 1),
        AssetMovementType.BUY,
    )
    _add_cotado_movement(
        world["db"], world["ws_id"], a.id, 10, 30, date(2026, 2, 1),
        AssetMovementType.SELL,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["quantity_held"] == Decimal("0")
    assert pos["total_invested_brl"] == Decimal("0")
    assert asset_has_position(pos, a) is False


def test_cotado_partial_sell_keeps_remaining_basis(world):
    """Spec 64 — sem regressão em cotado: STOCK BUY 10 + SELL 5."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.STOCK, current_price=30,
    )
    _add_cotado_movement(
        world["db"], world["ws_id"], a.id, 10, 25, date(2026, 1, 1),
        AssetMovementType.BUY,
    )
    _add_cotado_movement(
        world["db"], world["ws_id"], a.id, 5, 30, date(2026, 2, 1),
        AssetMovementType.SELL,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["quantity_held"] == Decimal("5")
    assert pos["average_cost_brl"] == Decimal("25")
    assert pos["total_invested_brl"] == Decimal("125")


def test_full_redemption_zeroes_both_cotado_and_non_cotado(world):
    """FULL_REDEMPTION deve resetar TUDO (semantic: fim total)."""
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=100_000,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=50_000, event_date=date(2026, 1, 1),
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=50_000, event_date=date(2026, 2, 1),
        mtype=AssetMovementType.FULL_REDEMPTION,
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    assert pos["total_invested_brl"] == Decimal("0")


def test_full_redemption_then_new_buy_reopens_position(world):
    """Após FULL_REDEMPTION, um novo BUY re-abre posição — has_position
    deve voltar True e current_value re-aparecer.
    """
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=30_000,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=50_000, event_date=date(2026, 1, 1),
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=50_000, event_date=date(2026, 2, 1),
        mtype=AssetMovementType.FULL_REDEMPTION,
    )
    # novo aporte após resgate
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=30_000, event_date=date(2026, 3, 1),
    )
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    # Posição re-aberta: current_value = current_price total (30k).
    assert pos["current_value"] == Decimal("30000")
    assert pos["total_invested_brl"] == Decimal("30000")


def test_fresh_manual_price_wins_over_stale_snapshot(world):
    """Bug 2026-07-07 audit — se o user atualiza asset.current_price
    DEPOIS do último snapshot fechar, o update manual deve vencer o
    valor frozen (que agora é o stale).
    """
    from numis_geek.models.portfolio_snapshot import (
        PortfolioSnapshot, PortfolioSnapshotItem, SnapshotStatus,
    )
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=90_000,
    )
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=50_000, event_date=date(2025, 1, 1),
    )
    # Snapshot CLOSED com valor VELHO (jan/26), fechado em jan/26
    old_close = datetime(2026, 1, 31, 20, 0, tzinfo=timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"],
        period_end_date=date(2026, 1, 31),
        fx_rate_usd_brl=Decimal("5.00"),
        total_value_brl=Decimal("50000"),
        total_value_usd=Decimal("10000"),
        total_invested_brl=Decimal("50000"),
        status=SnapshotStatus.CLOSED,
        closed_at=old_close, closed_by="test",
        is_active=True,
        created_at=old_close, updated_at=old_close,
    )
    world["db"].add(snap)
    world["db"].add(PortfolioSnapshotItem(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=a.id,
        quantity=Decimal("1"),
        unit_price=Decimal("50000"),
        market_value_native=Decimal("50000"),
        market_value_brl=Decimal("50000"),
        market_value_usd=Decimal("10000"),
        total_invested_brl=Decimal("50000"),
        created_at=old_close, updated_at=old_close,
    ))
    # User atualiza asset.current_price HOJE (jul/26) — mais recente que o snapshot.
    a.current_price = Decimal("90000")
    a.price_updated_at = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)
    world["db"].commit()

    pos = compute_position(world["db"], a.id, as_of=date(2026, 7, 7))
    # Manual update é POSTERIOR ao close do snapshot → respeita current_price.
    assert pos["current_value"] == Decimal("90000")


def test_yield_on_cost_hybrid_cotado_plus_non_cotado(world):
    """Fix C4 — yield_on_cost em asset híbrido soma AMBOS cotado
    e non_cotado no invested_native. Bug antigo (if/elif) descartava
    um lado silenciosamente.
    """
    from numis_geek.models.distribution import Distribution, DistributionType
    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FIXED_INCOME, current_price=15_000,
    )
    now = datetime.now(timezone.utc)
    # BUY cotado: 100 @ R$100 = R$10.000
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 1),
        quantity=Decimal("100"), unit_price=Decimal("100"),
        gross_amount=Decimal("10000"), net_amount=Decimal("10000"),
        currency=Currency.BRL,
    ))
    # BUY non_cotado: R$5.000
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 2, 1),
        quantity=None, unit_price=None,
        gross_amount=Decimal("5000"), net_amount=Decimal("5000"),
        currency=Currency.BRL,
    ))
    fi_id = world["db"].query(FinancialInstitution).first().id
    # Distribuição TTM: R$450 (yield_on_cost esperado = 450 / 15000 = 0.03)
    world["db"].add(Distribution(
        id=str(uuid.uuid4()),
        workspace_id=world["ws_id"], asset_id=a.id,
        financial_institution_id=fi_id,
        type=DistributionType.JCP,
        event_date=date(2026, 4, 1),
        gross_amount=Decimal("450"),
        net_amount=Decimal("450"),
        currency=Currency.BRL,
        fx_rate=Decimal("1"),
        is_active=True,
        created_at=now, updated_at=now,
    ))
    world["db"].commit()
    pos = compute_position(world["db"], a.id, as_of=date(2026, 6, 30))
    # invested_native = 100 × 100 (cotado) + 5000 (non_cotado) = 15000
    # yield_on_cost = 450 / 15000 = 0.03
    assert pos["yield_on_cost"] is not None
    assert abs(pos["yield_on_cost"] - Decimal("0.03")) < Decimal("0.0001")


# ── Fase 3.1 — _effective_item_quantity helper ─────────────────────────

def test_effective_item_quantity_forces_1_for_value_mode(world):
    """Fase 3.1: helper _effective_item_quantity retorna 1 pra value-mode."""
    from numis_geek.services.snapshot import _effective_item_quantity
    a_fund = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, current_price=0)
    a_prev = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.PRIVATE_PENSION, current_price=0)
    a_re = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.REAL_ESTATE, current_price=0)
    a_stock = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, current_price=0)
    # Value-mode: sempre 1 (mesmo com pos_qty=23)
    assert _effective_item_quantity(a_fund, Decimal("23")) == Decimal("1")
    assert _effective_item_quantity(a_prev, Decimal("0")) == Decimal("1")
    assert _effective_item_quantity(a_re, Decimal("999")) == Decimal("1")
    # Cotado: preserva pos_qty
    assert _effective_item_quantity(a_stock, Decimal("100")) == Decimal("100")
    assert _effective_item_quantity(a_stock, Decimal("0")) == Decimal("0")
    # None pos_qty vira 0 pra cotado (compat)
    assert _effective_item_quantity(a_stock, None) == Decimal("0")


def test_apply_recompute_value_mode_does_not_inflate_by_new_qty(world):
    """Fase 3.1: retro-lançamento em value-mode antes inflava
    mv_native em (N+1)/N. Com effective_qty=1 na persistência do item,
    mv_native = 1 × unit_price = valor total, mesmo com N+1 aportes.
    """
    from numis_geek.models.portfolio_snapshot import (
        PortfolioSnapshot, PortfolioSnapshotItem, SnapshotStatus,
    )
    from numis_geek.services.snapshot import apply_recompute_to_snapshot

    a = _make_asset(
        world["db"], world["ws_id"], world["account_id"],
        AssetClass.FUND, current_price=50_000,
    )
    # 3 aportes value-mode antes do snapshot
    for i in range(3):
        _add_value_mode_movement(
            world["db"], world["ws_id"], a.id,
            gross=15_000, event_date=date(2026, 1, 1 + i),
        )
    # Snapshot com valor frozen R$50k (item.quantity=1, unit_price=50000)
    now = datetime.now(timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"],
        period_end_date=date(2026, 3, 31),
        fx_rate_usd_brl=Decimal("5.00"),
        total_value_brl=Decimal("50000"),
        total_value_usd=Decimal("10000"),
        total_invested_brl=Decimal("45000"),
        status=SnapshotStatus.IN_REVIEW,
        is_active=True,
        created_at=now, updated_at=now,
    )
    world["db"].add(snap)
    item = PortfolioSnapshotItem(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=a.id,
        quantity=Decimal("1"),
        unit_price=Decimal("50000"),
        market_value_native=Decimal("50000"),
        market_value_brl=Decimal("50000"),
        market_value_usd=Decimal("10000"),
        total_invested_brl=Decimal("45000"),
        created_at=now, updated_at=now,
    )
    world["db"].add(item)
    world["db"].commit()

    # Retro-lançamento novo movement value-mode (agora total = 4 aportes)
    _add_value_mode_movement(
        world["db"], world["ws_id"], a.id,
        gross=15_000, event_date=date(2026, 2, 15),
    )

    # Recompute: pré-fix, item.quantity=4 e mv = 4 × 50000 = 200000 (bug).
    # Pós-fix, item.quantity=1 e mv = 1 × 50000 = 50000.
    apply_recompute_to_snapshot(
        world["db"], snapshot_id=snap.id, asset_id=a.id,
        user_id="test", trigger_event_type="movement", trigger_event_id="x",
    )
    world["db"].refresh(item)
    assert item.quantity == Decimal("1")
    assert item.market_value_native == Decimal("50000")
    assert item.market_value_brl == Decimal("50000")
