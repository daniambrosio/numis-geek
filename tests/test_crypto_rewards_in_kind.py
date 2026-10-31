"""Spec 66 — recompensa de cripto paga em cripto (Coinbase: USDC rewards em BTC).

O extrator emite um INTEREST com `payment_in_kind = {ticker, quantity}`; o
classificador transforma isso num par Distribution (provento do USDC) + BUY
(BTC recebido), deduplicado sem depender do valor em R$ — que o app da
exchange mostra diferente a cada dia.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.external import ExternalSource
from numis_geek.models.extraction_job import (
    ExtractionJob, ExtractionSourceHint, ExtractionStatus,
)
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotSource, SnapshotStatus,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services.extraction import (
    _apply_bulk_income_to_snapshot, preview_bulk_income,
)
from numis_geek.services.extraction_templates import BROKER_INCOME, BrokerIncomeOutput


def _world(db, *, snapshot_status=SnapshotStatus.IN_REVIEW):
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Coinbase", short_name="Coinbase",
        country="US", is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="Coinbase", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True,
    )
    db.add_all([ws, fi, acc])
    db.flush()

    def crypto(ticker: str) -> Asset:
        a = Asset(
            id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
            asset_class=AssetClass.CRYPTO, country="US", name=ticker, ticker=ticker,
            currency=Currency.BRL, price_source=PriceSource.MANUAL,
            is_active=True, created_at=now, updated_at=now,
        )
        db.add(a)
        return a

    usdc, btc = crypto("USDC"), crypto("BTC")
    db.flush()
    # 0.01 BTC comprado antes do mês, por R$ 3.000.
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=btc.id,
        type=AssetMovementType.BUY, event_date=date(2026, 8, 10),
        quantity=Decimal("0.01"), unit_price=Decimal("300000"),
        gross_amount=Decimal("3000"), net_amount=Decimal("3000"),
        currency=Currency.BRL, fx_rate=Decimal("5.5"), is_active=True,
        created_at=now, updated_at=now,
    ))
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id, period_end_date=date(2026, 9, 30),
        fx_rate_usd_brl=Decimal("5"),
        total_value_brl=Decimal("4000"), total_value_usd=Decimal("800"),
        total_invested_brl=Decimal("3000"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=snapshot_status,
    )
    db.add(snap)
    db.flush()
    # Item congelado ANTES das recompensas: 0.01 BTC @ R$ 400.000.
    btc_item = PortfolioSnapshotItem(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=btc.id,
        quantity=Decimal("0.01"), unit_price=Decimal("400000"),
        market_value_native=Decimal("4000"), market_value_brl=Decimal("4000"),
        market_value_usd=Decimal("800"),
        average_cost_brl=Decimal("300000"), total_invested_brl=Decimal("3000"),
        created_at=now,
    )
    db.add(btc_item)
    db.flush()
    return {"ws": ws, "fi": fi, "usdc": usdc, "btc": btc, "snap": snap, "btc_item": btc_item}


def _reward(event_date: str, brl: float, btc_qty: float | None, *, paid="BTC") -> dict:
    return {
        "event_date": event_date, "ticker_raw": "USDC", "type": "INTEREST",
        "gross_amount": brl, "tax_amount": None, "net_amount": brl,
        "currency": "BRL", "confidence": 0.95,
        "payment_in_kind": (
            {"ticker": paid, "quantity": btc_qty} if btc_qty is not None else None
        ),
    }


def _job(db, w, events: list[dict]) -> ExtractionJob:
    job = ExtractionJob(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id, snapshot_id=w["snap"].id,
        institution_id=w["fi"].id, attachment_id=str(uuid.uuid4()),
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        status=ExtractionStatus.EXTRACTED,
        extracted_json={"events": events, "option_events": []},
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()
    return job


def _apply(db, job):
    return _apply_bulk_income_to_snapshot(
        db, job, job.extracted_json, user_id=None, user_email="t@x.com",
    )


def _buys(db, w):
    return (
        db.query(AssetMovement)
        .filter(
            AssetMovement.asset_id == w["btc"].id,
            AssetMovement.external_source == ExternalSource.MANUAL_CSV,
        )
        .order_by(AssetMovement.event_date)
        .all()
    )


def test_template_v3_accepts_payment_in_kind():
    out = BrokerIncomeOutput.model_validate({"events": [_reward("2026-09-03", 189.15, 0.000471)]})
    assert out.events[0].payment_in_kind.ticker == "BTC"
    assert out.events[0].payment_in_kind.quantity == 0.000471
    assert BROKER_INCOME.version == "broker-income-v3"
    assert "payment_in_kind" in BROKER_INCOME.system
    # Sem o campo continua válido (proventos em dinheiro).
    plain = BrokerIncomeOutput.model_validate({"events": [{
        "event_date": "2026-09-03", "ticker_raw": "PETR4", "type": "DIVIDEND",
        "gross_amount": 10, "net_amount": 10, "confidence": 0.9,
    }]})
    assert plain.events[0].payment_in_kind is None


def test_preview_pairs_reward_with_in_kind_receipt(db):
    w = _world(db)
    job = _job(db, w, [_reward("2026-09-03", 189.15, 0.000471)])

    res = preview_bulk_income(db, job_id=job.id)

    assert res.errors == []
    [row] = res.bulk_detail.applied
    assert row["ticker"] == "USDC" and row["asset_id"] == w["usdc"].id
    assert row["in_kind"]["asset_id"] == w["btc"].id
    assert Decimal(row["in_kind"]["quantity"]) == Decimal("0.000471")
    # Preview não grava nada.
    assert db.query(Distribution).filter_by(workspace_id=w["ws"].id).count() == 0
    assert _buys(db, w) == []


def test_cash_reward_without_in_kind_keeps_single_row(db):
    w = _world(db)
    job = _job(db, w, [_reward("2026-09-03", 189.15, None)])

    res = _apply(db, job)

    assert res.applied_count == 1
    assert res.bulk_detail.applied[0]["in_kind"] is None
    assert _buys(db, w) == []


def test_apply_creates_distribution_and_buy_and_recomputes_item(db):
    w = _world(db)
    job = _job(db, w, [
        _reward("2026-09-03", 189.15, 0.000471),
        _reward("2026-09-10", 190.58, 0.00048),
    ])

    res = _apply(db, job)

    assert res.applied_count == 2
    dists = db.query(Distribution).filter_by(asset_id=w["usdc"].id).all()
    assert sorted(d.gross_amount for d in dists) == [Decimal("189.15"), Decimal("190.58")]
    assert all(d.type == DistributionType.INTEREST for d in dists)
    assert all("Coinbase" in d.notes and "avenue" not in d.notes for d in dists)

    buys = _buys(db, w)
    assert [b.quantity for b in buys] == [Decimal("0.000471"), Decimal("0.00048")]
    assert buys[0].gross_amount == Decimal("189.15")
    assert buys[0].unit_price == (Decimal("189.15") / Decimal("0.000471")).quantize(Decimal("1e-8"))
    assert buys[0].external_id.endswith(":in_kind")

    # Item do BTC no fechamento em revisão anda junto: qty, custo e valor
    # (preço congelado de R$ 400.000 preservado).
    item = w["btc_item"]
    db.refresh(item)
    assert item.quantity == Decimal("0.010951")
    assert item.unit_price == Decimal("400000")
    assert item.market_value_brl == Decimal("0.010951") * Decimal("400000")
    assert item.total_invested_brl == Decimal("3379.73")
    snap = w["snap"]
    db.refresh(snap)
    assert snap.total_value_brl == item.market_value_brl
    assert snap.status == SnapshotStatus.IN_REVIEW


def test_reupload_is_duplicate_even_when_brl_value_drifted(db):
    """O app da Coinbase mostra outro valor em R$ no dia seguinte — o par
    tem que ser reconhecido pela data + ativo, não pelo valor."""
    w = _world(db)
    _apply(db, _job(db, w, [_reward("2026-09-03", 189.15, 0.000471)]))

    res = _apply(db, _job(db, w, [_reward("2026-09-03", 190.02, 0.000471)]))

    assert res.applied_count == 0
    assert len(res.bulk_detail.matched_no_pendency) == 1
    assert len(_buys(db, w)) == 1
    assert db.query(Distribution).filter_by(asset_id=w["usdc"].id).count() == 1


def test_manual_pair_with_other_external_id_is_duplicate(db):
    """Regressão julho/26: o par lançado à mão (external_id `coinbase-reward:*`)
    foi duplicado pela extração, que gera `coinbase:*:INTEREST:*`."""
    w = _world(db)
    now = datetime.now(timezone.utc)
    db.add(Distribution(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id,
        financial_institution_id=w["fi"].id, asset_id=w["usdc"].id,
        type=DistributionType.INTEREST, event_date=date(2026, 9, 3),
        gross_amount=Decimal("187.72"), net_amount=Decimal("187.72"),
        currency=Currency.BRL, fx_rate=Decimal("1"), is_active=True,
        external_id="coinbase-reward:2026-09-03:USDC:187.72",
        external_source=ExternalSource.MANUAL_CSV, created_at=now, updated_at=now,
    ))
    db.flush()

    res = _apply(db, _job(db, w, [_reward("2026-09-03", 189.15, 0.000471)]))

    assert res.applied_count == 0
    assert len(res.bulk_detail.matched_no_pendency) == 1
    assert _buys(db, w) == []


def test_existing_buy_with_same_quantity_marks_pair_duplicate(db):
    w = _world(db)
    now = datetime.now(timezone.utc)
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id, asset_id=w["btc"].id,
        type=AssetMovementType.BUY, event_date=date(2026, 9, 3),
        quantity=Decimal("0.000471"), unit_price=Decimal("401592"),
        gross_amount=Decimal("189.15"), net_amount=Decimal("189.15"),
        currency=Currency.BRL, fx_rate=Decimal("5.4"), is_active=True,
        created_at=now, updated_at=now,
    ))
    db.flush()

    res = _apply(db, _job(db, w, [_reward("2026-09-03", 189.15, 0.000471)]))

    assert res.applied_count == 0
    assert db.query(Distribution).filter_by(asset_id=w["usdc"].id).count() == 0


def test_unknown_paid_asset_orphans_whole_pair(db):
    w = _world(db)

    res = _apply(db, _job(db, w, [_reward("2026-09-03", 189.15, 0.5, paid="ETH")]))

    assert res.applied_count == 0
    [orphan] = res.bulk_detail.orphan
    assert "ETH" in orphan["orphan_reason"]
    assert db.query(Distribution).filter_by(asset_id=w["usdc"].id).count() == 0


def test_reward_paid_in_same_asset(db):
    """Se a recompensa vier no próprio USDC, o aporte entra no USDC."""
    w = _world(db)

    _apply(db, _job(db, w, [_reward("2026-09-03", 189.15, 35.12, paid="USDC")]))

    buys = (
        db.query(AssetMovement)
        .filter_by(asset_id=w["usdc"].id, type=AssetMovementType.BUY)
        .all()
    )
    assert [b.quantity for b in buys] == [Decimal("35.12")]


def test_invalid_in_kind_quantity_is_error(db):
    w = _world(db)

    res = _apply(db, _job(db, w, [_reward("2026-09-03", 189.15, 0)]))

    assert res.applied_count == 0
    assert any("payment_in_kind" in e for e in res.errors)


def test_failure_mid_apply_leaves_nothing(db, monkeypatch):
    """Par atômico: se o BUY falha, o provento não fica sozinho (o commit
    é do request; aqui a exceção sobe e o rollback descarta os dois)."""
    import numis_geek.services.extraction as ex

    w = _world(db)
    job = _job(db, w, [_reward("2026-09-03", 189.15, 0.000471)])
    db.commit()

    def boom(*a, **k):
        raise RuntimeError("fx indisponível")
    monkeypatch.setattr(ex, "resolve_fx_rate", boom)

    try:
        _apply(db, job)
    except RuntimeError:
        db.rollback()
    else:  # pragma: no cover
        raise AssertionError("apply deveria ter falhado")

    assert db.query(Distribution).filter_by(asset_id=w["usdc"].id).count() == 0
    assert _buys(db, w) == []
