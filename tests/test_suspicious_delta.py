"""Spec 62 — Detecção de variações anômalas no fechamento.

Testa: threshold por asset_class, native currency, movement/CA suppress,
skip novo/zerado, block close, auto-resolve, regression BHIA3+FundoVerde.
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
from numis_geek.models.corporate_action import CorporateAction, CorporateActionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PendencyAction,
    PendencyReason,
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotPendency,
    SnapshotStatus,
)
from numis_geek.services.snapshot import (
    PendencyOpenError,
    confirm_delta_pendency,
    confirm_snapshot,
    create_snapshot,
    detect_suspicious_deltas,
    list_mom_deltas,
    update_snapshot_item_price,
)
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
    ws = WorkspaceService(db).create(f"SD WS {uuid.uuid4().hex[:8]}")
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP",
        logo_slug="xp", is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    account = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="Investment",
        account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(account)
    db.commit()
    yield {"db": db, "ws_id": ws.id, "account_id": account.id, "fi_id": fi.id, "now": now}
    db.close()


def _make_asset(
    db, ws_id, account_id, asset_class, current_price=None, currency=Currency.BRL,
    name=None,
):
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_id, account_id=account_id,
        asset_class=asset_class, country="BR",
        name=name or f"Test {asset_class.value}",
        ticker=None, currency=currency, is_active=True,
        current_price=Decimal(str(current_price)) if current_price is not None else None,
        created_at=now, updated_at=now,
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


def _snap(db, ws_id, period_end, items: list[tuple[str, Decimal]], status=SnapshotStatus.CLOSED):
    """Cria snapshot manualmente com items (asset_id, mv_native) — não
    passa pelo pipeline detect. Útil pra preparar o "mês anterior"."""
    now = datetime.now(timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws_id,
        period_end_date=period_end, fx_rate_usd_brl=Decimal("5.00"),
        total_value_brl=sum(mv for _, mv in items) or Decimal("0"),
        total_value_usd=Decimal("0"), total_invested_brl=Decimal("0"),
        status=status, closed_at=now if status == SnapshotStatus.CLOSED else None,
        closed_by="test" if status == SnapshotStatus.CLOSED else None,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(snap)
    for asset_id, mv in items:
        db.add(PortfolioSnapshotItem(
            id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=asset_id,
            quantity=Decimal("1"), unit_price=mv,
            market_value_native=mv, market_value_brl=mv,
            market_value_usd=mv / Decimal("5"),
            total_invested_brl=mv, created_at=now, updated_at=now,
        ))
    db.commit()
    return snap


# ── Threshold per asset_class ──────────────────────────────────────────

def test_threshold_fund_flags_at_20_percent(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 60_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("60000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1  # 20% > 15% threshold FUND


def test_threshold_stock_does_not_flag_at_30_percent(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, 130)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("100"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("130"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert ids == []  # 30% < 40% threshold STOCK


def test_threshold_stock_flags_at_50_percent(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, 150)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("100"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("150"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1


def test_threshold_cash_flags_at_25_percent(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.CASH, 12_500)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("10000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("12500"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1  # 25% > 20% CASH


# ── Movement suppression ───────────────────────────────────────────────

def test_movement_in_period_suppresses_flag(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    # BUY no período justifica o pulo
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 6, 15),
        quantity=Decimal("1"), unit_price=Decimal("40000"),
        gross_amount=Decimal("40000"), net_amount=Decimal("40000"),
        currency=Currency.BRL,
    ))
    world["db"].commit()
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("100000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert ids == []


def test_ca_in_period_suppresses_flag(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, 200)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("100"))])
    # SPLIT 2:1 no período
    now = world["now"]
    world["db"].add(CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=a.id,
        event_type=CorporateActionType.SPLIT, event_date=date(2026, 6, 10),
        ratio=Decimal("2"), is_active=True,
        created_at=now, updated_at=now,
    ))
    world["db"].commit()
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("200"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert ids == []  # 100% delta mas CA justifica


# ── Skip new / zeroed ──────────────────────────────────────────────────

def test_new_asset_no_flag(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [])  # sem item pro asset
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("100000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert ids == []


def test_zeroed_asset_no_flag(world):
    """Ativo com posição no mês anterior, ausente no atual — ZEROED,
    provavelmente saída legítima. Sem flag."""
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 0)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert ids == []


# ── Bloqueio + resolução ───────────────────────────────────────────────

def test_confirm_snapshot_blocked_by_open_suspicious_delta(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("100000"))], status=SnapshotStatus.IN_REVIEW)
    detect_suspicious_deltas(world["db"], snap.id)
    with pytest.raises(PendencyOpenError):
        confirm_snapshot(world["db"], snapshot_id=snap.id, user_id="u1")


def test_confirm_delta_pendency_unblocks_close(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("100000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1
    confirm_delta_pendency(
        world["db"], pendency_id=ids[0], user_id="u1",
        note="cotas valorizaram",
    )
    result = confirm_snapshot(world["db"], snapshot_id=snap.id, user_id="u1")
    assert result.status == SnapshotStatus.CLOSED


def test_confirm_delta_rejects_wrong_reason(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000)
    now = world["now"]
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("100000"))], status=SnapshotStatus.IN_REVIEW)
    other_pen = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=a.id,
        reason=PendencyReason.HISTORICAL_PRICE_REQUIRED,
        action_type=PendencyAction.EDIT_PRICE, detail=None,
        created_at=now,
    )
    world["db"].add(other_pen); world["db"].commit()
    with pytest.raises(ValueError, match="not SUSPICIOUS_DELTA"):
        confirm_delta_pendency(world["db"], pendency_id=other_pen.id, user_id="u1")


def test_update_price_auto_resolves_when_below_threshold(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("100000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1
    # User corrige o preço pra R$55k (10% delta, abaixo do 15% FUND)
    update_snapshot_item_price(
        world["db"], snapshot_id=snap.id, asset_id=a.id,
        new_price=Decimal("55000"), user_id="u1",
        value_mode="total",
    )
    pen = world["db"].get(SnapshotPendency, ids[0])
    assert pen.resolved_at is not None


# ── Native currency vs BRL ─────────────────────────────────────────────

def test_delta_uses_native_currency_not_brl(world):
    """USD asset com PTAX subindo 20% mas mv_native flat → sem flag.
    (Range é forçado pelo mv_native manual — não simula PTAX real)."""
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, 100, currency=Currency.USD)
    # Snapshot anterior USD 1000
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("1000"))])
    # Este mês mesmo USD 1000
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("1000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert ids == []


# ── Regression bugs históricos ─────────────────────────────────────────

def test_regression_bhia3_stale_3x(world):
    """BHIA3 bug: item mv_native 3× o real por stale — deveria flagar."""
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, 250)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("30000"))])
    # Snapshot atual com 3× o valor (stale bug)
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("90000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1  # 200% > 40% STOCK


def test_regression_fundo_verde_btg_massive_drop(world):
    """Fundo Verde BTG bug: R$ 81.912 → R$ 1,72 (drop ~100%)."""
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, Decimal("1.72"))
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("81912"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("1.72"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1  # ~100% > 15% FUND


# ── list_mom_deltas view ───────────────────────────────────────────────

def test_list_mom_deltas_includes_ok_and_suspicious(world):
    a_ok = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, 105, name="OK Stock")
    a_susp = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000, name="Suspicious FUND")
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [
        (a_ok.id, Decimal("100")),
        (a_susp.id, Decimal("50000")),
    ])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [
        (a_ok.id, Decimal("105")),
        (a_susp.id, Decimal("100000")),
    ], status=SnapshotStatus.IN_REVIEW)
    detect_suspicious_deltas(world["db"], snap.id)

    rows = list_mom_deltas(world["db"], snap.id)
    statuses = {r.asset_id: r.status for r in rows}
    assert statuses[a_ok.id] == "OK"
    assert statuses[a_susp.id] == "SUSPICIOUS_PENDING"
    # Ordenado por magnitude — suspicious (delta 50k) vem antes de OK (delta 5)
    assert rows[0].asset_id == a_susp.id


def test_list_mom_deltas_includes_new_and_zeroed(world):
    a_new = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, 100, name="New")
    a_gone = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, 0, name="Gone")
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a_gone.id, Decimal("500"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a_new.id, Decimal("300"))], status=SnapshotStatus.IN_REVIEW)
    rows = list_mom_deltas(world["db"], snap.id)
    statuses = {r.asset_id: r.status for r in rows}
    assert statuses[a_new.id] == "NEW"
    assert statuses[a_gone.id] == "ZEROED"


def test_no_previous_snapshot_returns_no_pendencies(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000)
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("100000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert ids == []
    rows = list_mom_deltas(world["db"], snap.id)
    assert all(r.status == "NEW" for r in rows)


def test_detect_is_idempotent(world):
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("100000"))], status=SnapshotStatus.IN_REVIEW)
    ids1 = detect_suspicious_deltas(world["db"], snap.id)
    ids2 = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids1) == 1
    assert ids2 == []  # segunda chamada não cria duplicata


# ── Bugs achados no audit: filtros e escalação ────────────────────────

def test_come_cotas_movement_does_not_suppress_flag(world):
    """Bug audit spec 62 — COME_COTAS é tax-only, não muda posição. Um
    delta de 20% em FUND não deve ser suprimido só porque houve
    come-cotas no período."""
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 60_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.COME_COTAS, event_date=date(2026, 6, 15),
        quantity=Decimal("0"), unit_price=Decimal("0"),
        gross_amount=Decimal("0"), tax=Decimal("500"),
        net_amount=Decimal("-500"), currency=Currency.BRL,
    ))
    world["db"].commit()
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("60000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1  # come-cotas NÃO deve suprimir


def test_reevaluate_updates_stale_detail_when_delta_grows(world):
    """Bug audit spec 62 — se o user editou pra um valor pior, a
    pendency existente NÃO é auto-resolved mas o detail é atualizado
    pra refletir o novo delta em vez de ficar stale."""
    import json
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 60_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("60000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    pen = world["db"].get(SnapshotPendency, ids[0])
    old_detail = json.loads(pen.detail)
    assert Decimal(old_detail["current_mv_native"]) == Decimal("60000")

    # User edita pra 200k (delta 300%, muito PIOR).
    update_snapshot_item_price(
        world["db"], snapshot_id=snap.id, asset_id=a.id,
        new_price=Decimal("200000"), user_id="u1", value_mode="total",
    )
    world["db"].refresh(pen)
    assert pen.resolved_at is None  # ainda aberta
    new_detail = json.loads(pen.detail)
    assert Decimal(new_detail["current_mv_native"]) == Decimal("200000")


def test_update_snapshot_item_price_creates_new_delta_if_out_of_range(world):
    """Bug audit spec 62 CRITICAL — se user editou preço pra fora do
    threshold em um asset SEM SUSPICIOUS_DELTA anterior, deveria criar
    pendency nova (antes só _reevaluate rodava, deixando delta passar
    batido no CLOSE)."""
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 51_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    # Snapshot com valor OK (2% delta, abaixo do 15%)
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("51000"))], status=SnapshotStatus.IN_REVIEW)
    detect_suspicious_deltas(world["db"], snap.id)
    open_pens = world["db"].query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == snap.id,
        SnapshotPendency.resolved_at.is_(None),
    ).count()
    assert open_pens == 0

    # User edita pra 100k (100% delta, muito acima)
    update_snapshot_item_price(
        world["db"], snapshot_id=snap.id, asset_id=a.id,
        new_price=Decimal("100000"), user_id="u1", value_mode="total",
    )
    # DEVE ter criado SUSPICIOUS_DELTA agora
    open_pens_after = world["db"].query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == snap.id,
        SnapshotPendency.reason == PendencyReason.SUSPICIOUS_DELTA,
        SnapshotPendency.resolved_at.is_(None),
    ).count()
    assert open_pens_after == 1


def test_hybrid_cotado_plus_non_cotado_delta_detected(world):
    """Batch C bug motivation — asset híbrido (cotado + non_cotado)
    tinha total_invested_brl bugado; mv_native pode ter valor real,
    então detect trata como qualquer outro."""
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FIXED_INCOME, 25_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("15000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("25000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1  # 66% > 15% FIXED_INCOME


def test_delete_snapshot_item_removes_pendency(world):
    """delete_snapshot_item deve remover SUSPICIOUS_DELTA junto."""
    from numis_geek.services.snapshot import delete_snapshot_item
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 100_000)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("50000"))])
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("100000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert len(ids) == 1

    delete_snapshot_item(
        world["db"], snapshot_id=snap.id, asset_id=a.id, user_id="u1",
    )
    pen = world["db"].get(SnapshotPendency, ids[0])
    assert pen is None  # deletada em cascade


def test_snapshot_anterior_in_review_is_skipped(world):
    """_previous_closed_snapshot filtra por status=CLOSED. Se o snapshot
    anterior está IN_REVIEW (reopen retroativo), pula ele e vai pro
    anterior ao anterior. Testa comportamento (mesmo mês).
    """
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.FUND, 55_000)
    _snap(world["db"], world["ws_id"], date(2026, 4, 30), [(a.id, Decimal("50000"))])
    # mai/26 em IN_REVIEW com valor MUITO diferente (não deve ser usado)
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("500000"))], status=SnapshotStatus.IN_REVIEW)
    # jun/26 comparado com abr/26 (mai é IN_REVIEW): delta 10% do 50k → OK
    snap = _snap(world["db"], world["ws_id"], date(2026, 6, 30), [(a.id, Decimal("55000"))], status=SnapshotStatus.IN_REVIEW)
    ids = detect_suspicious_deltas(world["db"], snap.id)
    assert ids == []  # 10% < 15% FUND (comparado ao 50k de abr, não 500k de mai)


def test_create_snapshot_downgrades_to_in_review_on_suspicious(world):
    """create_snapshot com pendency SUSPICIOUS_DELTA deve downgrade
    initial_status=CLOSED pra IN_REVIEW. Uso STOCK (asset cotado) pra
    não conflitar com o frozen-fallback do Batch C que reescreveria
    current_price=50k a partir do snap anterior."""
    a = _make_asset(world["db"], world["ws_id"], world["account_id"], AssetClass.STOCK, current_price=100)
    # BUY em jan/26: 100 @ R$30 = R$3000
    world["db"].add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=a.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 1),
        quantity=Decimal("100"), unit_price=Decimal("30"),
        gross_amount=Decimal("3000"), net_amount=Decimal("3000"),
        currency=Currency.BRL,
    ))
    world["db"].commit()
    # Snapshot anterior com mv 3000 (100 × 30). Threshold STOCK = 40%.
    _snap(world["db"], world["ws_id"], date(2026, 5, 31), [(a.id, Decimal("3000"))])
    r = create_snapshot(
        world["db"], workspace_id=world["ws_id"], period_end=date(2026, 6, 30),
        user_id="u1", initial_status=SnapshotStatus.CLOSED,
    )
    # current_price=100, mv = 100 × 100 = 10000. Delta (10000-3000)/3000 = 233% > 40%.
    # sem movement em (mai, jun] → deveria criar pendency + downgrade.
    assert r.status == SnapshotStatus.IN_REVIEW
    assert r.pendencies_count >= 1
