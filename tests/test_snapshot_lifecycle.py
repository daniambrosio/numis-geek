"""Spec 35 — tests for snapshot lifecycle, pendency detection, confirm/reopen,
resolve, retry-api, and audit emission."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.integrations.brapi import BrapiQuote
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    CredentialTestResult,
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.models.portfolio_snapshot import (
    PendencyAction,
    PendencyReason,
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotPendency,
    SnapshotStatus,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services.snapshot import (
    PendencyOpenError,
    add_snapshot_item,
    apply_recompute_to_snapshot,
    apply_skip_recompute,
    confirm_snapshot,
    create_snapshot,
    delete_snapshot_item,
    detect_pendencies,
    find_affected_snapshots,
    reopen_snapshot,
    resolve_pendency,
    retry_pendency_api,
    sync_snapshot_items,
    update_snapshot_item_price,
)


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


NOW = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
PERIOD = date(2026, 4, 30)


def _seed(db, *, with_brapi_token: bool = True) -> dict:
    """Standard world: 1 BRAPI fresh, 1 FINNHUB stale, 1 MANUAL real estate,
    1 Avenue generic UPLOAD case, 1 BRAPI old (stale-price), 1 inactive."""
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="Spec35 WS")
    fi_xp = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    fi_avenue = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Avenue", short_name="Avenue", logo_slug="avenue",
        is_active=True, created_at=now, updated_at=now,
    )
    fi_particular = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Particular", short_name="Particular", logo_slug="particular",
        is_active=True, created_at=now, updated_at=now,
    )
    acc_xp = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi_xp.id,
        name="XP", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    acc_avenue = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi_avenue.id,
        name="Avenue", account_type=AccountType.investment, currency=Currency.USD,
        is_active=True, created_at=now, updated_at=now,
    )
    acc_part = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi_particular.id,
        name="Particular", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    petr = Asset(  # BRAPI fresh
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_xp.id,
        asset_class=AssetClass.STOCK, country="BR", name="Petrobras", ticker="PETR4",
        currency=Currency.BRL, current_price=Decimal("38.50"),
        price_updated_at=NOW - timedelta(hours=2),
        price_source=PriceSource.BRAPI,
        is_active=True, created_at=now, updated_at=now,
    )
    petr_stale = Asset(  # BRAPI > 7d → STALE_PRICE
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_xp.id,
        asset_class=AssetClass.STOCK, country="BR", name="Vale", ticker="VALE3",
        currency=Currency.BRL, current_price=Decimal("60.0"),
        price_updated_at=NOW - timedelta(days=10),
        price_source=PriceSource.BRAPI,
        is_active=True, created_at=now, updated_at=now,
    )
    aapl_neverrefreshed = Asset(  # FINNHUB never refreshed → API_FAILED
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_avenue.id,
        asset_class=AssetClass.STOCK, country="US", name="Apple", ticker="AAPL",
        currency=Currency.USD, current_price=None,
        price_updated_at=None,
        price_source=PriceSource.FINNHUB,
        is_active=True, created_at=now, updated_at=now,
    )
    casa = Asset(  # MANUAL real estate → MANUAL_SOURCE
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_part.id,
        asset_class=AssetClass.REAL_ESTATE, country="BR", name="Casa", ticker=None,
        currency=Currency.BRL, current_price=Decimal("820000"),
        price_updated_at=NOW - timedelta(days=20),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    avenue_generic = Asset(  # MANUAL + Avenue + no ticker → UPLOAD_REQUIRED
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_avenue.id,
        asset_class=AssetClass.FIXED_INCOME, country="US",
        name="Avenue Rendimentos", ticker=None,
        currency=Currency.USD, current_price=Decimal("1234.56"),
        price_updated_at=NOW - timedelta(days=5),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    cash = Asset(  # No source → skipped
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_part.id,
        asset_class=AssetClass.CASH, country="BR", name="Saldo", ticker=None,
        currency=Currency.BRL, current_price=Decimal("1000"),
        price_source=None,
        is_active=True, created_at=now, updated_at=now,
    )

    db.add_all([
        ws, fi_xp, fi_avenue, fi_particular,
        acc_xp, acc_avenue, acc_part,
        petr, petr_stale, aapl_neverrefreshed, casa, avenue_generic, cash,
    ])

    # Movements so qty > 0
    from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
    for a, qty, price in [
        (petr, Decimal("100"), Decimal("30")),
        (petr_stale, Decimal("50"), Decimal("70")),
        (aapl_neverrefreshed, Decimal("10"), Decimal("150")),
        (casa, Decimal("1"), Decimal("820000")),
        (avenue_generic, Decimal("1"), Decimal("1000")),
    ]:
        db.add(AssetMovement(
            id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=a.id,
            type=AssetMovementType.BUY, event_date=date(2026, 1, 10),
            quantity=qty, unit_price=price,
            gross_amount=qty * price, net_amount=qty * price,
            currency=a.currency, fx_rate=Decimal("5.0") if a.currency == Currency.USD else Decimal("1"),
            is_active=True, created_at=now, updated_at=now,
        ))

    # PTAX for period_end
    from numis_geek.models.ptax_rate import PTAXRate
    db.add(PTAXRate(
        id=str(uuid.uuid4()), date=PERIOD, rate=Decimal("5.10"),
        source="BCB_SGS", fetched_at=now,
    ))

    if with_brapi_token:
        db.add(IntegrationCredential(
            id=str(uuid.uuid4()), workspace_id=None,
            provider=IntegrationProvider.BRAPI, key_name="API_TOKEN",
            secret_value="brapi-token", is_active=True,
            last_test_result=CredentialTestResult.UNTESTED,
            created_at=now, updated_at=now,
        ))

    db.flush()
    return {
        "ws_id": ws.id,
        "petr_id": petr.id,
        "petr_stale_id": petr_stale.id,
        "aapl_id": aapl_neverrefreshed.id,
        "casa_id": casa.id,
        "avenue_generic_id": avenue_generic.id,
        "cash_id": cash.id,
    }


# ── detect_pendencies ──────────────────────────────────────────────────────


def test_detect_no_pendency_for_fresh_brapi(db):
    w = _seed(db)
    asset = db.get(Asset, w["petr_id"])
    assert detect_pendencies(db, asset, period_end=PERIOD, now=NOW) is None


def test_detect_stale_price_when_brapi_older_than_7d(db):
    w = _seed(db)
    asset = db.get(Asset, w["petr_stale_id"])
    det = detect_pendencies(db, asset, period_end=PERIOD, now=NOW)
    assert det is not None
    reason, action, _ = det
    assert reason == PendencyReason.STALE_PRICE
    assert action == PendencyAction.RETRY_API


def test_detect_api_failed_when_finnhub_never_refreshed(db):
    w = _seed(db)
    asset = db.get(Asset, w["aapl_id"])
    det = detect_pendencies(db, asset, period_end=PERIOD, now=NOW)
    assert det is not None
    assert det[0] == PendencyReason.API_FAILED
    assert det[1] == PendencyAction.RETRY_API


def test_detect_manual_source(db):
    w = _seed(db)
    asset = db.get(Asset, w["casa_id"])
    det = detect_pendencies(db, asset, period_end=PERIOD, now=NOW)
    assert det is not None
    assert det[0] == PendencyReason.MANUAL_SOURCE
    assert det[1] == PendencyAction.EDIT_PRICE


def test_detect_upload_required_for_avenue_generic(db):
    w = _seed(db)
    asset = db.get(Asset, w["avenue_generic_id"])
    det = detect_pendencies(db, asset, period_end=PERIOD, now=NOW)
    assert det is not None
    assert det[0] == PendencyReason.UPLOAD_REQUIRED
    assert det[1] == PendencyAction.UPLOAD_FILE


def test_detect_skips_no_source_assets(db):
    w = _seed(db)
    asset = db.get(Asset, w["cash_id"])
    assert detect_pendencies(db, asset, period_end=PERIOD, now=NOW) is None


# ── create_snapshot lifecycle ──────────────────────────────────────────────


def test_create_snapshot_downgrades_to_in_review_when_pendencies(db):
    w = _seed(db)
    result = create_snapshot(
        db, workspace_id=w["ws_id"], period_end=PERIOD, now=NOW,
    )
    assert result.status == SnapshotStatus.IN_REVIEW
    # 4 pendencies expected (petr_stale, aapl, casa, avenue_generic).
    assert result.pendencies_count == 4


def test_create_snapshot_closes_when_no_pendencies(db):
    """Empty world (no assets) → no pendencies → snapshot stays CLOSED."""
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="Empty WS")
    db.add(ws)
    db.flush()
    result = create_snapshot(
        db, workspace_id=ws.id, period_end=PERIOD,
    )
    assert result.status == SnapshotStatus.CLOSED
    assert result.pendencies_count == 0


# ── confirm / reopen ────────────────────────────────────────────────────────


def test_confirm_refuses_with_open_pendencies(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    with pytest.raises(PendencyOpenError):
        confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")


def test_confirm_succeeds_after_resolving_all(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Resolve each pendency
    pens = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all()
    for pen in pens:
        resolve_pendency(
            db, pendency_id=pen.id, user_id="alice",
            new_price=Decimal("99.99"),
        )
    snap = confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")
    assert snap.status == SnapshotStatus.CLOSED
    assert snap.closed_at is not None
    assert snap.closed_by == "alice"


def test_confirm_recomputes_total_invested_brl_from_items(db):
    """Bug 4 regression — header total_invested_brl ficava stale quando
    items eram editados/sincronizados após create_snapshot. confirm deve
    re-agregar dos items pra garantir consistência."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    for pen in db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all():
        resolve_pendency(
            db, pendency_id=pen.id, user_id="alice",
            new_price=Decimal("99.99"),
        )

    # Suja o header artificialmente — simula divergência criada por
    # patches/syncs após create_snapshot.
    snap_before = db.query(PortfolioSnapshot).get(r.snapshot_id)
    snap_before.total_invested_brl = Decimal("999999999.99")
    db.flush()

    snap = confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")
    items_sum = sum(
        (i.total_invested_brl or Decimal("0"))
        for i in db.query(PortfolioSnapshotItem).filter(
            PortfolioSnapshotItem.snapshot_id == snap.id
        )
    )
    assert snap.total_invested_brl == items_sum


def test_reopen_moves_to_in_review_and_redetects(db):
    """Confirm then reopen — new pendencies recreated from current state."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Resolve everything and confirm.
    pens = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all()
    for pen in pens:
        resolve_pendency(
            db, pendency_id=pen.id, user_id="alice",
            new_price=Decimal("99.99"),
        )
    confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")

    # Reopen.
    snap = reopen_snapshot(
        db, snapshot_id=r.snapshot_id, user_id="alice",
        reason="found a wrong distribution",
    )
    assert snap.status == SnapshotStatus.IN_REVIEW
    assert snap.closed_at is None
    # New pendencies recreated from current state.
    new_pens = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all()
    # The MANUAL ones still pending; the API ones either re-pending or not
    # depending on detection logic (we resolved them via new_price, but the
    # underlying price_source is still MANUAL/Avenue/etc).
    assert len(new_pens) >= 1


def test_reopen_skips_pendency_when_item_has_frozen_price(db):
    """2026-06-09 incident 2 — reopen de snapshot que veio do NOTION_BACKFILL
    (CLOSED com items mas sem pendencies históricas) recriava 59
    pendencies fantasmas porque detect_pendencies só olha pra
    asset.price_source (sempre MANUAL pra fundos/imóveis/previdência).
    Items que já têm unit_price/market_value frozen são implicitamente
    resolvidos — não criar pendency."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    for pen in db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all():
        resolve_pendency(db, pendency_id=pen.id, user_id="alice",
                         new_price=Decimal("100"))
    confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")

    # Simula um snapshot vindo do backfill: items COM preço, ZERO
    # pendencies. Deleto todas pra repetir esse cenário.
    db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).delete()
    db.flush()

    reopen_snapshot(
        db, snapshot_id=r.snapshot_id, user_id="alice",
        reason="lançamento retroativo",
    )

    # Nenhuma pendency fantasma — todos os items tinham unit_price.
    new_pens = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id,
    ).count()
    assert new_pens == 0, (
        f"reopen criou {new_pens} pendencies fantasmas em items com preço frozen"
    )


def test_reopen_preserves_resolved_pendencies(db):
    """2026-06-09 regression — reopen anterior apagava TODAS as
    pendencies, inclusive resolvidas. Lançamento retroativo auto-reopen
    fazia o user perder o status 'resolvido' de dezenas de ativos."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)

    # Resolve TODAS as pendencies + confirm.
    pens_before = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all()
    for pen in pens_before:
        resolve_pendency(
            db, pendency_id=pen.id, user_id="alice",
            new_price=Decimal("100"),
        )
    confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")
    resolved_count_before = len(pens_before)
    assert resolved_count_before >= 2  # sanity

    # Reopen — não pode apagar as resolvidas.
    reopen_snapshot(
        db, snapshot_id=r.snapshot_id, user_id="alice",
        reason="retroactive movement",
    )

    pens_after = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id,
        SnapshotPendency.resolved_at.isnot(None),
    ).all()
    assert len(pens_after) == resolved_count_before, (
        f"reopen apagou pendencies resolvidas: "
        f"{resolved_count_before} antes → {len(pens_after)} depois"
    )


# ── resolve ────────────────────────────────────────────────────────────────


def test_resolve_pendency_updates_asset_price(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    pen = (
        db.query(SnapshotPendency)
        .filter(
            SnapshotPendency.snapshot_id == r.snapshot_id,
            SnapshotPendency.asset_id == w["casa_id"],
        )
        .first()
    )
    assert pen is not None
    before = db.get(Asset, w["casa_id"]).current_price
    resolve_pendency(
        db, pendency_id=pen.id, user_id="alice",
        new_price=Decimal("850000"),
    )
    after = db.get(Asset, w["casa_id"]).current_price
    assert after == Decimal("850000")
    assert after != before
    # Pendency is marked resolved
    pen2 = db.get(SnapshotPendency, pen.id)
    assert pen2.resolved_at is not None
    assert pen2.resolved_by == "alice"


# ── retry-api ──────────────────────────────────────────────────────────────


def test_retry_api_resolves_when_refresh_succeeds(db):
    # Spec 52 — retry só funciona em snapshot de hoje (refresh_one
    # retorna preço LIVE; em snapshot antigo seria corrupção). Esse
    # teste valida o happy path: snapshot do dia + API mock OK.
    w = _seed(db)
    today = date.today()
    # PTAX pra today (seed só cria pro PERIOD; precisa pra fx_rate).
    from numis_geek.models.ptax_rate import PTAXRate
    if db.query(PTAXRate).filter(PTAXRate.date == today).first() is None:
        db.add(PTAXRate(
            id=str(uuid.uuid4()), date=today, rate=Decimal("5.10"),
            source="BCB_SGS", fetched_at=datetime.now(timezone.utc),
        ))
        db.flush()
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=today)
    pen = (
        db.query(SnapshotPendency)
        .filter(
            SnapshotPendency.snapshot_id == r.snapshot_id,
            SnapshotPendency.asset_id == w["petr_stale_id"],
        )
        .first()
    )
    assert pen is not None
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="VALE3", price=Decimal("65.0")),
    ):
        pen2 = retry_pendency_api(
            db, pendency_id=pen.id, user_id="alice",
        )
    db.refresh(pen2)
    assert pen2.resolved_at is not None
    assert "ok" in (pen2.resolution_note or "")


# ── audit emission ──────────────────────────────────────────────────────────


def test_confirm_emits_audit(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Force a clean confirm — resolve everything
    for pen in db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all():
        resolve_pendency(db, pendency_id=pen.id, user_id="alice",
                         new_price=Decimal("100"))
    confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")
    audit = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.confirm",
        AuditLog.resource_id == r.snapshot_id,
    ).first()
    assert audit is not None


def test_reopen_emits_audit(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    for pen in db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all():
        resolve_pendency(db, pendency_id=pen.id, user_id="alice",
                         new_price=Decimal("100"))
    confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")
    reopen_snapshot(
        db, snapshot_id=r.snapshot_id, user_id="alice",
        reason="test reopen",
    )
    audit = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.reopen",
        AuditLog.resource_id == r.snapshot_id,
    ).first()
    assert audit is not None
    assert "test reopen" in (audit.details or "")


def test_resolve_emits_audit(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    pen = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).first()
    resolve_pendency(db, pendency_id=pen.id, user_id="alice",
                     new_price=Decimal("100"), note="my note")
    audit = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.pendency.resolve",
        AuditLog.resource_id == pen.id,
    ).first()
    assert audit is not None
    assert "my note" in (audit.details or "")


# ── Spec 49 hotfix #11 — zero-price + delete item ──────────────────────────


def test_update_snapshot_item_accepts_zero_price(db):
    """Spec 49 hotfix #11 — setting a snapshot item price to 0 must work.

    Used when a retroactive movement zeroes out an asset already frozen
    in the snapshot."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    item = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id
    ).first()
    assert item is not None
    update_snapshot_item_price(
        db,
        snapshot_id=r.snapshot_id,
        asset_id=item.asset_id,
        user_id="alice",
        new_price=Decimal("0"),
        value_mode="total",
    )
    refreshed = db.get(PortfolioSnapshotItem, item.id)
    assert refreshed.unit_price == Decimal("0")
    assert refreshed.market_value_native == Decimal("0")
    assert refreshed.market_value_brl == Decimal("0")


def test_update_snapshot_item_price_overrides_quantity(db):
    """2026-07-01 — permitir sobrescrever item.quantity via patch para
    bater com extrato do custodiante quando o histórico de movements ficou
    fora de sincronia (bonificação/come-cotas não capturada). O qty
    fornecido reescreve item.quantity; o market_value é recomputado a
    partir dele + preço."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    item = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id
    ).first()
    assert item is not None
    original_qty = item.quantity

    updated = update_snapshot_item_price(
        db,
        snapshot_id=r.snapshot_id,
        asset_id=item.asset_id,
        user_id="alice",
        new_price=Decimal("80199"),
        value_mode="total",
        new_quantity=Decimal("16040"),
    )
    assert updated.quantity == Decimal("16040")
    assert updated.quantity != original_qty
    # market_value = new_quantity * (total / new_quantity) = total
    assert updated.market_value_native == Decimal("80199")
    # unit_price derivado do total ÷ NOVA qty (não da original)
    assert updated.unit_price == Decimal("80199") / Decimal("16040")


def test_update_snapshot_item_price_keeps_quantity_when_omitted(db):
    """Regressão: patch sem `new_quantity` mantém o qty existente."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    item = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id
    ).first()
    assert item is not None
    original_qty = item.quantity

    updated = update_snapshot_item_price(
        db,
        snapshot_id=r.snapshot_id,
        asset_id=item.asset_id,
        user_id="alice",
        new_price=Decimal("100"),
        value_mode="unit",
    )
    assert updated.quantity == original_qty


def test_delete_snapshot_item_removes_item_and_pendency(db):
    """Spec 49 hotfix #11 — deleting an item drops the row, drops any
    pendency for that asset, and refreshes the snapshot's totals."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    snap = db.get(PortfolioSnapshot, r.snapshot_id)
    item = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id
    ).first()
    asset_id = item.asset_id
    before_total = snap.total_value_brl

    delete_snapshot_item(
        db,
        snapshot_id=r.snapshot_id,
        asset_id=asset_id,
        user_id="alice",
    )

    assert db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == asset_id,
    ).count() == 0
    assert db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id,
        SnapshotPendency.asset_id == asset_id,
    ).count() == 0
    db.refresh(snap)
    assert snap.total_value_brl <= before_total

    audit = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.item.delete",
    ).first()
    assert audit is not None


def test_delete_snapshot_item_refuses_closed_snapshot(db):
    """CLOSED snapshots must be reopened before items can be deleted."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Resolve everything and close
    for pen in db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all():
        resolve_pendency(db, pendency_id=pen.id, user_id="alice",
                         new_price=Decimal("100"))
    confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")

    item = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id
    ).first()
    with pytest.raises(ValueError, match="CLOSED"):
        delete_snapshot_item(
            db,
            snapshot_id=r.snapshot_id,
            asset_id=item.asset_id,
            user_id="alice",
        )


# ── Spec 49 hotfix #12 — VALUE-mode assets in snapshot ────────────────────


def _add_value_mode_asset(db, ws_id: str, account_id: str, *, name: str,
                          invested_brl: Decimal) -> str:
    """Create a VALUE-mode asset (PRIVATE_PENSION) with a single
    quantity=NULL BUY recorded only by gross_amount. Mirrors how XP
    previdência rows are entered in production."""
    from numis_geek.models.asset_movement import (
        AssetMovement, AssetMovementType,
    )
    now = datetime.now(timezone.utc)
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_id, account_id=account_id,
        asset_class=AssetClass.PRIVATE_PENSION, country="BR", name=name,
        ticker=None, currency=Currency.BRL, current_price=None,
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(asset)
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws_id, asset_id=asset.id,
        type=AssetMovementType.BUY, event_date=date(2025, 8, 15),
        quantity=None, unit_price=None,
        gross_amount=invested_brl, net_amount=invested_brl,
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()
    return asset.id


def test_create_snapshot_includes_value_mode_assets(db):
    """Spec 49 hotfix #12 — a PRIVATE_PENSION asset with quantity=NULL
    (modo valor puro) must appear in the snapshot."""
    w = _seed(db)
    prev_id = _add_value_mode_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="Trend Pós-Fixado Previdência",
        invested_brl=Decimal("50000"),
    )
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    items = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == prev_id,
    ).all()
    assert len(items) == 1, "VALUE-mode asset must appear in the snapshot"
    assert items[0].total_invested_brl == Decimal("50000")
    # qty is 0, market_value depends on current_price (NULL → mv NULL).
    assert items[0].quantity == Decimal("0")


def test_reopen_snapshot_adds_missing_value_mode_assets(db):
    """Spec 49 hotfix #12 — reopen recovers VALUE-mode assets that
    pre-existed but were excluded by the historical `qty == 0` guard."""
    w = _seed(db)
    # Snapshot first, before the value-mode asset exists.
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    pre_count = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id
    ).count()
    # Now add a value-mode asset retroactively (movement event_date before
    # period_end). reopen should pick it up.
    prev_id = _add_value_mode_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="XP Corporate Light Previdência",
        invested_brl=Decimal("80000"),
    )
    reopen_snapshot(
        db, snapshot_id=r.snapshot_id, user_id="alice",
        reason="recover value-mode asset",
    )
    post_items = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id
    ).all()
    assert len(post_items) == pre_count + 1
    added = [it for it in post_items if it.asset_id == prev_id]
    assert len(added) == 1
    assert added[0].total_invested_brl == Decimal("80000")


def test_asset_has_position_centralized_rule(db):
    """The helper handles both modes: qty>0 (cotado) and basis>0 (valor)."""
    from numis_geek.services.positions import asset_has_position
    # Cotado mode
    w = _seed(db)
    from numis_geek.services.positions import compute_position
    pos = compute_position(db, w["petr_id"], as_of=PERIOD)
    assert asset_has_position(pos) is True
    # Valor mode
    prev_id = _add_value_mode_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="VGBL teste", invested_brl=Decimal("10000"),
    )
    pos_val = compute_position(db, prev_id, as_of=PERIOD)
    assert pos_val["quantity_held"] == Decimal("0")
    assert pos_val["total_invested_brl"] == Decimal("10000")
    assert asset_has_position(pos_val) is True
    # Neither (empty position)
    empty: dict = {"quantity_held": Decimal("0"), "total_invested_brl": Decimal("0")}
    assert asset_has_position(empty) is False  # type: ignore[arg-type]


def test_sync_snapshot_items_in_review_adds_missing(db):
    """Spec 49 hotfix #12 — sync endpoint covers IN_REVIEW snapshots
    that the user can't reopen."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    snap = db.get(PortfolioSnapshot, r.snapshot_id)
    assert snap.status == SnapshotStatus.IN_REVIEW
    pre_count = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id
    ).count()
    prev_id = _add_value_mode_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="Trend Prev FIRF (retro)",
        invested_brl=Decimal("70000"),
    )
    result = sync_snapshot_items(
        db, snapshot_id=r.snapshot_id, user_id="alice",
    )
    assert result["items_added"] == 1
    post_count = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id
    ).count()
    assert post_count == pre_count + 1
    added = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == prev_id,
    ).one()
    assert added.total_invested_brl == Decimal("70000")


def test_sync_snapshot_items_refuses_closed(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    for pen in db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all():
        resolve_pendency(db, pendency_id=pen.id, user_id="alice",
                         new_price=Decimal("100"))
    confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")
    with pytest.raises(ValueError, match="CLOSED"):
        sync_snapshot_items(db, snapshot_id=r.snapshot_id, user_id="alice")


def test_add_snapshot_item_manual_basic(db):
    """Manual single-asset add works for IN_REVIEW snapshots."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    new_asset_id = _add_value_mode_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="VGBL XP Seg Prev", invested_brl=Decimal("25000"),
    )
    item = add_snapshot_item(
        db, snapshot_id=r.snapshot_id, asset_id=new_asset_id, user_id="alice",
    )
    assert item is not None
    assert item.snapshot_id == r.snapshot_id
    assert item.asset_id == new_asset_id


def test_add_snapshot_item_refuses_duplicate(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # petr is already in the snapshot via _seed/create_snapshot
    with pytest.raises(ValueError, match="already in snapshot"):
        add_snapshot_item(
            db, snapshot_id=r.snapshot_id, asset_id=w["petr_id"], user_id="alice",
        )


def test_add_snapshot_item_refuses_inactive_asset(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Create an inactive asset
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=w["ws_id"],
        account_id=db.get(Asset, w["petr_id"]).account_id,
        asset_class=AssetClass.STOCK, country="BR", name="DEAD", ticker="XPTO",
        currency=Currency.BRL, is_active=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(asset)
    db.flush()
    with pytest.raises(ValueError, match="inactive"):
        add_snapshot_item(
            db, snapshot_id=r.snapshot_id, asset_id=asset.id, user_id="alice",
        )


def test_add_snapshot_item_refuses_closed_snapshot(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    for pen in db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all():
        resolve_pendency(db, pendency_id=pen.id, user_id="alice",
                         new_price=Decimal("100"))
    confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")
    new_asset_id = _add_value_mode_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="VGBL retro", invested_brl=Decimal("10000"),
    )
    with pytest.raises(ValueError, match="CLOSED"):
        add_snapshot_item(
            db, snapshot_id=r.snapshot_id, asset_id=new_asset_id, user_id="alice",
        )


# ── Spec 51 — Retroactive Event Reconciliation ────────────────────────────


def _add_buy_movement(db, ws_id: str, asset_id: str, event_date: date,
                      qty: str, price: str) -> str:
    """Helper: cria um BUY simples ativo."""
    from numis_geek.models.asset_movement import (
        AssetMovement, AssetMovementType,
    )
    now = datetime.now(timezone.utc)
    qty_d = Decimal(qty)
    price_d = Decimal(price)
    mov = AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws_id, asset_id=asset_id,
        type=AssetMovementType.BUY, event_date=event_date,
        quantity=qty_d, unit_price=price_d,
        gross_amount=qty_d * price_d, net_amount=qty_d * price_d,
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(mov)
    db.flush()
    return mov.id


def test_find_affected_snapshots_detects_qty_change(db):
    """Spec 51 — adicionar BUY retroativo deve aparecer como afetado
    em todo snapshot >= event_date."""
    w = _seed(db)
    # Cria snapshot inicial.
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Lança BUY retroativo na semana anterior ao period_end.
    new_qty_d = Decimal("50")
    _add_buy_movement(
        db, w["ws_id"], w["petr_id"], PERIOD - timedelta(days=5),
        qty=str(new_qty_d), price="40",
    )
    affected = find_affected_snapshots(
        db, workspace_id=w["ws_id"], asset_id=w["petr_id"],
        earliest_event_date=PERIOD - timedelta(days=5),
    )
    assert len(affected) == 1
    a = affected[0]
    assert a.snapshot_id == r.snapshot_id
    # Seed BUY=100, novo BUY=50 → 150.
    assert a.old_quantity == Decimal("100")
    assert a.new_quantity == Decimal("150")


def test_find_affected_snapshots_skips_unchanged(db):
    """Snapshot sem nenhum movimento retroativo não deve aparecer."""
    w = _seed(db)
    create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    affected = find_affected_snapshots(
        db, workspace_id=w["ws_id"], asset_id=w["petr_id"],
        earliest_event_date=PERIOD - timedelta(days=10),
    )
    assert affected == []


def test_find_affected_snapshots_handles_value_mode(db):
    """Ativo VALUE-puro com BUY retroativo deve ser detectado pelo
    delta de total_invested_brl, mesmo com qty=0."""
    w = _seed(db)
    prev_id = _add_value_mode_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="VGBL impacto retro", invested_brl=Decimal("10000"),
    )
    create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Agora simula aporte adicional retroativo no fundo:
    from numis_geek.models.asset_movement import (
        AssetMovement, AssetMovementType,
    )
    now = datetime.now(timezone.utc)
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=w["ws_id"], asset_id=prev_id,
        type=AssetMovementType.BUY,
        event_date=PERIOD - timedelta(days=2),
        quantity=None, unit_price=None,
        gross_amount=Decimal("5000"), net_amount=Decimal("5000"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()
    affected = find_affected_snapshots(
        db, workspace_id=w["ws_id"], asset_id=prev_id,
        earliest_event_date=PERIOD - timedelta(days=2),
    )
    assert len(affected) == 1
    a = affected[0]
    assert a.old_total_invested_brl == Decimal("10000")
    assert a.new_total_invested_brl == Decimal("15000")
    assert a.old_quantity == Decimal("0")
    assert a.new_quantity == Decimal("0")


def test_apply_recompute_auto_reopens_closed(db):
    """Snapshot CLOSED deve ser reaberto automaticamente com reason
    rastreável ao trigger event. Quando todas as pendencies anteriores
    estavam resolvidas, o recompute também fecha de volta (sem deixar
    o user com 'EM REVISÃO' alarmante sem necessidade)."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Resolve tudo + close.
    for pen in db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id
    ).all():
        resolve_pendency(db, pendency_id=pen.id, user_id="alice",
                         new_price=Decimal("100"))
    confirm_snapshot(db, snapshot_id=r.snapshot_id, user_id="alice")
    snap = db.get(PortfolioSnapshot, r.snapshot_id)
    assert snap.status == SnapshotStatus.CLOSED

    mov_id = _add_buy_movement(
        db, w["ws_id"], w["petr_id"], PERIOD - timedelta(days=3),
        qty="50", price="40",
    )
    apply_recompute_to_snapshot(
        db,
        snapshot_id=r.snapshot_id,
        asset_id=w["petr_id"],
        trigger_event_type="asset_movement.create",
        trigger_event_id=mov_id,
        user_id="alice",
    )
    snap = db.get(PortfolioSnapshot, r.snapshot_id)
    # 2026-06-09 — todas as pendencies estavam resolvidas + recompute
    # tocou só esse asset → auto-reclose pra evitar "EM REVISÃO"
    # alarmante. Audit do recompute marca auto_reopened + auto_reclosed.
    assert snap.status == SnapshotStatus.CLOSED

    # Audit log do reopen ainda menciona o trigger event.
    reopen_audit = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.reopen",
        AuditLog.resource_id == r.snapshot_id,
    ).first()
    assert reopen_audit is not None
    assert mov_id in (reopen_audit.details or "")

    recompute_audit = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.item.recompute",
    ).order_by(AuditLog.created_at.desc()).first()
    assert recompute_audit is not None
    assert '"auto_reclosed": true' in (recompute_audit.details or "")


def test_apply_recompute_uses_snapshot_fx_rate(db):
    """fx_rate do snapshot é frozen — recompute NÃO deve buscar PTAX
    do dia atual pra recalcular USD."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    snap = db.get(PortfolioSnapshot, r.snapshot_id)
    fx_at_snapshot = snap.fx_rate_usd_brl
    assert fx_at_snapshot is not None

    # Movimento retroativo no AAPL (USD).
    aapl = db.get(Asset, w["aapl_id"])
    aapl.current_price = Decimal("200")  # ajusta pra que o item tenha mv > 0
    db.flush()
    mov_id = _add_buy_movement(
        db, w["ws_id"], w["aapl_id"], PERIOD - timedelta(days=3),
        qty="5", price="180",
    )
    # Garante que o ativo tem fx_rate pro snapshot via current_price
    item = apply_recompute_to_snapshot(
        db,
        snapshot_id=r.snapshot_id,
        asset_id=w["aapl_id"],
        trigger_event_type="asset_movement.create",
        trigger_event_id=mov_id,
        user_id="alice",
    )
    if item.market_value_brl is not None and item.market_value_usd is not None:
        # market_value_brl / market_value_usd deve bater com o fx do snapshot.
        ratio = item.market_value_brl / item.market_value_usd
        assert abs(ratio - fx_at_snapshot) < Decimal("0.0001")


def test_apply_recompute_logs_audit_with_delta(db):
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    mov_id = _add_buy_movement(
        db, w["ws_id"], w["petr_id"], PERIOD - timedelta(days=3),
        qty="50", price="40",
    )
    apply_recompute_to_snapshot(
        db,
        snapshot_id=r.snapshot_id,
        asset_id=w["petr_id"],
        trigger_event_type="asset_movement.create",
        trigger_event_id=mov_id,
        user_id="alice",
    )
    audit = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.item.recompute",
    ).first()
    assert audit is not None
    details = audit.details or ""
    assert mov_id in details
    assert "before" in details
    assert "after" in details


def test_skip_recompute_then_drift_query_via_audit(db):
    """Bloco 3 — após skip, query do audit log pelo
    resource_id='{snap}:{asset}' devolve a entrada (fonte do drift panel)."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    mov_id = _add_buy_movement(
        db, w["ws_id"], w["petr_id"], PERIOD - timedelta(days=3),
        qty="50", price="40",
    )
    apply_skip_recompute(
        db,
        snapshot_id=r.snapshot_id,
        asset_id=w["petr_id"],
        trigger_event_type="asset_movement.create",
        trigger_event_id=mov_id,
        reason="ajusto manualmente depois",
        user_id="alice",
    )
    expected_rid = f"{r.snapshot_id}:{w['petr_id']}"
    rows = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.recompute.skipped",
        AuditLog.resource_id == expected_rid,
    ).all()
    assert len(rows) == 1
    import json as _json
    details = _json.loads(rows[0].details)
    assert details["reason"] == "ajusto manualmente depois"
    assert details["trigger_event_id"] == mov_id
    assert details["asset_id"] == w["petr_id"]


def test_apply_skip_recompute_logs_only(db):
    """Skip não muda nenhum dado — só registra audit log."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    mov_id = _add_buy_movement(
        db, w["ws_id"], w["petr_id"], PERIOD - timedelta(days=3),
        qty="50", price="40",
    )
    item_before = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == w["petr_id"],
    ).one()
    qty_before = item_before.quantity
    apply_skip_recompute(
        db,
        snapshot_id=r.snapshot_id,
        asset_id=w["petr_id"],
        trigger_event_type="asset_movement.create",
        trigger_event_id=mov_id,
        reason="prefiro manter o histórico como estava",
        user_id="alice",
    )
    item_after = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == w["petr_id"],
    ).one()
    assert item_after.quantity == qty_before
    audit = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.recompute.skipped",
    ).first()
    assert audit is not None
    assert "prefiro manter" in (audit.details or "")


# ── Spec 52 — Snapshot Price Immutability ──────────────────────────────────


def _new_asset(db, ws_id: str, account_id: str, *, name: str, ticker: str,
               source: PriceSource = PriceSource.MANUAL,
               current_price: Decimal = Decimal("50")) -> str:
    """Cria ativo SEM movimento — pra simular asset que nem existia
    quando o snapshot foi criado."""
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_id, account_id=account_id,
        asset_class=AssetClass.STOCK, country="BR", name=name, ticker=ticker,
        currency=Currency.BRL, current_price=current_price,
        price_updated_at=NOW, price_source=source,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(a)
    db.flush()
    return a.id


def test_apply_recompute_preserves_frozen_unit_price(db):
    """Spec 52 — recompute de item existente NÃO sobrescreve unit_price
    com asset.current_price. Pre-condição clássica do bug: snapshot
    criado num preço, bulk refresh mudou current_price depois, mov
    retroativa dispara recompute, e o item DEVE ficar com o preço
    frozen do period_end (não o LIVE)."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    item_before = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == w["petr_id"],
    ).one()
    frozen_price = item_before.unit_price
    assert frozen_price is not None

    # Simula bulk refresh: preço LIVE mudou DEPOIS da criação do snapshot.
    petr = db.get(Asset, w["petr_id"])
    petr.current_price = frozen_price + Decimal("100")
    db.flush()

    # Movimento retroativo: muda quantidade no period_end.
    new_qty_d = Decimal("25")
    mov_id = _add_buy_movement(
        db, w["ws_id"], w["petr_id"], PERIOD - timedelta(days=3),
        qty=str(new_qty_d), price="40",
    )

    apply_recompute_to_snapshot(
        db, snapshot_id=r.snapshot_id, asset_id=w["petr_id"],
        trigger_event_type="asset_movement.create", trigger_event_id=mov_id,
        user_id="alice",
    )
    item_after = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == w["petr_id"],
    ).one()
    # ❶ unit_price frozen — não LIVE.
    assert item_after.unit_price == frozen_price
    # ❷ quantidade nova (100 + 25 = 125).
    assert item_after.quantity == Decimal("125")
    # ❸ market_value = qty × frozen (NÃO qty × LIVE).
    assert item_after.market_value_native == Decimal("125") * frozen_price


def test_apply_recompute_new_item_in_old_snapshot_creates_pendency(db):
    """Spec 52 — item NOVO em snapshot antigo (period_end no passado):
    não escreve LIVE price, escreve unit_price=None + cria pendency
    HISTORICAL_PRICE_REQUIRED + EDIT_PRICE."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Asset novo (criado APÓS o snapshot) — não está no snapshot ainda.
    new_id = _new_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="Novo BBSE3", ticker="BBSE3",
        current_price=Decimal("999"),  # LIVE — não pode vazar
    )
    # Movimento retroativo cria posição no period_end.
    mov_id = _add_buy_movement(
        db, w["ws_id"], new_id, PERIOD - timedelta(days=2),
        qty="10", price="30",
    )

    item = apply_recompute_to_snapshot(
        db, snapshot_id=r.snapshot_id, asset_id=new_id,
        trigger_event_type="asset_movement.create", trigger_event_id=mov_id,
        user_id="alice",
    )
    assert item.unit_price is None  # NÃO vazou current_price=999
    assert item.market_value_native is None
    assert item.market_value_brl is None

    pen = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id,
        SnapshotPendency.asset_id == new_id,
    ).one()
    assert pen.reason == PendencyReason.HISTORICAL_PRICE_REQUIRED
    assert pen.action_type == PendencyAction.EDIT_PRICE


def test_apply_recompute_new_item_today_uses_current_price(db):
    """Spec 52 — quando period_end == today, é a 'primeira captura';
    pode usar pos['current_price'] sem virar pendency."""
    w = _seed(db)
    today = date.today()
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=today)
    new_id = _new_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="Hoje SA", ticker="HOJE3",
        current_price=Decimal("77"),
    )
    mov_id = _add_buy_movement(
        db, w["ws_id"], new_id, today - timedelta(days=1),
        qty="10", price="50",
    )
    item = apply_recompute_to_snapshot(
        db, snapshot_id=r.snapshot_id, asset_id=new_id,
        trigger_event_type="asset_movement.create", trigger_event_id=mov_id,
        user_id="alice",
    )
    assert item.unit_price == Decimal("77")  # current_price OK pra hoje
    # Sem pendency HISTORICAL_PRICE_REQUIRED.
    pen = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id,
        SnapshotPendency.asset_id == new_id,
        SnapshotPendency.reason == PendencyReason.HISTORICAL_PRICE_REQUIRED,
    ).first()
    assert pen is None


def test_add_snapshot_item_old_snapshot_creates_pendency(db):
    """Spec 52 — add_snapshot_item em snapshot antigo: pendency, não LIVE."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Reabre se necessário (PERIOD pode ter sido fechado pelo seed?).
    snap = db.get(PortfolioSnapshot, r.snapshot_id)
    if snap.status == SnapshotStatus.CLOSED:
        reopen_snapshot(
            db, snapshot_id=snap.id, user_id="alice", reason="test",
        )

    new_id = _new_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="ADD SA", ticker="ADDD3",
        current_price=Decimal("321"),
    )
    _add_buy_movement(
        db, w["ws_id"], new_id, PERIOD - timedelta(days=2),
        qty="5", price="100",
    )
    item = add_snapshot_item(
        db, snapshot_id=r.snapshot_id, asset_id=new_id,
        user_id="alice",
    )
    assert item.unit_price is None  # NÃO vazou current_price=321
    pen = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id,
        SnapshotPendency.asset_id == new_id,
        SnapshotPendency.reason == PendencyReason.HISTORICAL_PRICE_REQUIRED,
    ).one()
    assert pen.action_type == PendencyAction.EDIT_PRICE


def test_sync_snapshot_items_old_snapshot_creates_pendency(db):
    """Spec 52 — sync_snapshot_items em snapshot antigo:
    items adicionados ficam sem unit_price + pendency."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    snap = db.get(PortfolioSnapshot, r.snapshot_id)
    if snap.status == SnapshotStatus.CLOSED:
        reopen_snapshot(
            db, snapshot_id=snap.id, user_id="alice", reason="test",
        )

    # Cria asset + mov RETROATIVA que dá posição no period_end. Não
    # mexe no snapshot existente (sync vai detectar e adicionar).
    new_id = _new_asset(
        db, w["ws_id"], db.get(Asset, w["petr_id"]).account_id,
        name="SYNC SA", ticker="SYNC3",
        current_price=Decimal("888"),
    )
    _add_buy_movement(
        db, w["ws_id"], new_id, PERIOD - timedelta(days=2),
        qty="3", price="200",
    )

    result = sync_snapshot_items(
        db, snapshot_id=r.snapshot_id, user_id="alice",
    )
    assert result["items_added"] >= 1

    item = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == new_id,
    ).one()
    assert item.unit_price is None  # NÃO vazou current_price=888

    pen = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id,
        SnapshotPendency.asset_id == new_id,
        SnapshotPendency.reason == PendencyReason.HISTORICAL_PRICE_REQUIRED,
    ).one()
    assert pen.action_type == PendencyAction.EDIT_PRICE


def test_retry_pendency_api_rejects_old_snapshot(db):
    """Spec 52 — refresh_one chama API LIVE. Em snapshot antigo isso
    corrompe o histórico, então a operação deve falhar."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    # Pendency RETRY_API existe pro AAPL (FINNHUB never refreshed).
    pen = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == r.snapshot_id,
        SnapshotPendency.action_type == PendencyAction.RETRY_API,
    ).first()
    assert pen is not None  # seed garante essa pendency

    with pytest.raises(ValueError, match="Snapshot antigo"):
        retry_pendency_api(
            db, pendency_id=pen.id, user_id="alice",
        )


def test_find_affected_snapshots_preview_uses_frozen_price(db):
    """Spec 52 — preview da modal AffectedSnapshotsModal NÃO deve usar
    LIVE price pra calcular new_market_value_brl. Item existente →
    preview usa existing.unit_price (frozen)."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    item = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == w["petr_id"],
    ).one()
    frozen_price = item.unit_price

    # Simula bulk refresh DEPOIS do snapshot.
    petr = db.get(Asset, w["petr_id"])
    live_price = frozen_price + Decimal("50")
    petr.current_price = live_price
    db.flush()

    # Adiciona movimento retroativo.
    _add_buy_movement(
        db, w["ws_id"], w["petr_id"], PERIOD - timedelta(days=3),
        qty="10", price="40",
    )

    affected = find_affected_snapshots(
        db, workspace_id=w["ws_id"], asset_id=w["petr_id"],
        earliest_event_date=PERIOD - timedelta(days=3),
    )
    assert len(affected) == 1
    a = affected[0]
    # 110 × frozen, NÃO 110 × live. fx_rate p/ BRL é 1 (asset BRL).
    expected = Decimal("110") * frozen_price
    assert a.new_market_value_brl == expected


# ── Spec sessão 2026-06-06: modo-VALOR resolve_pendency ────────────────────


def test_resolve_pendency_modo_valor_qty_zero_sets_market_value_to_typed_value(db):
    """Bug 2026-06-06: ativo modo-VALOR (Previdência, FGTS, FIM/FIC) tem
    quantity_held=0 porque movement é non_cotado (qty=NULL, gross_only).
    Quando o user resolve a pendência tipando o valor total do extrato,
    o código antigo fazia `mv = item.quantity * unit_price = 0 * 53385 = 0`
    e o fechamento mostrava R$ 0. Fix: pra qty=0 modo-VALOR, market_value
    = new_price direto (já é o total)."""
    w = _seed(db)
    # Adiciona um Previdência (PRIVATE_PENSION) no workspace com movement
    # non-cotado (gross_only). Isso reproduz o XP Corp Light.
    now = datetime.now(timezone.utc)
    asset_id = str(uuid.uuid4())
    acc_id = db.query(Account).first().id
    prev = Asset(
        id=asset_id, workspace_id=w["ws_id"], account_id=acc_id,
        asset_class=AssetClass.PRIVATE_PENSION, country="BR",
        name="XP Seg Prev Test", ticker=None,
        currency=Currency.BRL, current_price=None,
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(prev)
    from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=w["ws_id"], asset_id=asset_id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 5),
        quantity=None, unit_price=None,
        gross_amount=Decimal("50000"), net_amount=Decimal("50000"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()

    # Cria snapshot — modo-VALOR é detectado por _sync_missing_value_mode_items
    # via create_snapshot → asset_has_position retorna True por
    # total_invested_brl != 0.
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    pen = (
        db.query(SnapshotPendency)
        .filter(
            SnapshotPendency.snapshot_id == r.snapshot_id,
            SnapshotPendency.asset_id == asset_id,
        )
        .first()
    )
    assert pen is not None, "modo-VALOR asset deve gerar pendência"

    # User digita o valor total do extrato (R$ 53.385,74)
    typed_value = Decimal("53385.74")
    resolve_pendency(
        db, pendency_id=pen.id, user_id="alice",
        new_price=typed_value,
    )

    # CRÍTICO: market_value_brl deve ser o valor digitado, NÃO 0.
    item = (
        db.query(PortfolioSnapshotItem)
        .filter(
            PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
            PortfolioSnapshotItem.asset_id == asset_id,
        )
        .one()
    )
    assert item.quantity == Decimal("0")
    assert item.unit_price == typed_value
    assert item.market_value_native == typed_value, (
        f"market_value_native = {item.market_value_native}, esperado {typed_value}"
    )
    assert item.market_value_brl == typed_value, (
        f"market_value_brl = {item.market_value_brl}, esperado {typed_value}"
    )


def test_update_snapshot_item_price_marks_open_pendency_resolved(db):
    """Spec sessão 2026-06-06: o modal de edição (clique em "Editar" na
    Posições Congeladas OU em "Editar" numa pendência) chama o mesmo
    endpoint PATCH /snapshots/{id}/items/{asset_id}. Antes, a pendência
    ficava em aberto se o user editava por esse caminho. Agora
    update_snapshot_item_price marca a pendência aberta como resolved."""
    w = _seed(db)
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)
    pen = (
        db.query(SnapshotPendency)
        .filter(
            SnapshotPendency.snapshot_id == r.snapshot_id,
            SnapshotPendency.asset_id == w["casa_id"],
        )
        .first()
    )
    assert pen is not None
    assert pen.resolved_at is None

    update_snapshot_item_price(
        db,
        snapshot_id=r.snapshot_id, asset_id=w["casa_id"],
        user_id="alice", new_price=Decimal("900000"),
        value_mode="total", note="lendo o extrato",
    )
    pen2 = db.get(SnapshotPendency, pen.id)
    assert pen2.resolved_at is not None
    assert pen2.resolved_by == "alice"
    assert pen2.resolution_note == "lendo o extrato"


def test_update_snapshot_item_price_modo_valor_qty_zero(db):
    """Mesma garantia do resolve_pendency: pra qty=0 (modo VALOR), o
    market_value vira o new_price direto, não 0."""
    w = _seed(db)
    now = datetime.now(timezone.utc)
    asset_id = str(uuid.uuid4())
    acc_id = db.query(Account).first().id
    prev = Asset(
        id=asset_id, workspace_id=w["ws_id"], account_id=acc_id,
        asset_class=AssetClass.PRIVATE_PENSION, country="BR",
        name="Prev V2 Test", ticker=None,
        currency=Currency.BRL, current_price=None,
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(prev)
    from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=w["ws_id"], asset_id=asset_id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 5),
        quantity=None, unit_price=None,
        gross_amount=Decimal("50000"), net_amount=Decimal("50000"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()
    r = create_snapshot(db, workspace_id=w["ws_id"], period_end=PERIOD)

    typed = Decimal("53385.74")
    item = update_snapshot_item_price(
        db, snapshot_id=r.snapshot_id, asset_id=asset_id,
        user_id="alice", new_price=typed, value_mode="total",
    )
    assert item.quantity == Decimal("0")
    assert item.market_value_brl == typed, f"got {item.market_value_brl}"
