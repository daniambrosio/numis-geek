"""Regression guards para bugs financeiros que já aconteceram em produção.

Cada teste protege um invariante que, se quebrado por um refactor futuro,
reintroduz um bug conhecido. Ver o docstring de cada teste para o incidente
de origem e a memória associada.

Padrão adotado: engine SQLite in-memory module-scoped, session per-test com
rollback, seguindo test_snapshot_lifecycle.py.
"""
from __future__ import annotations

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
import numis_geek.models  # noqa: F401  — registra todos os modelos no metadata
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.corporate_action import (
    CorporateAction, CorporateActionType,
)
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.extraction_job import (
    ExtractionJob,
    ExtractionSourceHint,
    ExtractionStatus,
)
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services import extraction as extraction_service
from numis_geek.services.auth import AuthService
from numis_geek.services.positions import asset_has_position, compute_position
from numis_geek.services.snapshot import (
    apply_recompute_to_snapshot,
    confirm_snapshot,
    create_snapshot,
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


# ── helpers compartilhados ─────────────────────────────────────────────────


def _seed_ws(db, *, ptax_date: date | None = None, ptax_rate: Decimal = Decimal("5.10")):
    """Workspace mínimo: 1 FI XP (BRL) + 1 FI Avenue (USD) + 2 contas
    investment + PTAX opcional na data pedida."""
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name=f"WS-{uuid.uuid4().hex[:6]}")
    fi_xp = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    fi_av = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Avenue", short_name="Avenue",
        country="US", is_active=True, created_at=now, updated_at=now,
    )
    acc_brl = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_xp.id, name="XP Inv",
        account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    acc_usd = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_av.id, name="Avenue Inv",
        account_type=AccountType.investment, currency=Currency.USD,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi_xp, fi_av, acc_brl, acc_usd])
    if ptax_date is not None:
        db.add(PTAXRate(
            id=str(uuid.uuid4()), date=ptax_date, rate=ptax_rate,
            source="BCB_SGS", fetched_at=now,
        ))
    db.flush()
    return {
        "ws": ws, "fi_xp": fi_xp, "fi_av": fi_av,
        "acc_brl": acc_brl, "acc_usd": acc_usd, "now": now,
    }


def _mk_user(db, ws_id: str | None, *, role: UserRole,
             email: str | None = None, password: str = "pw") -> User:
    now = datetime.now(timezone.utc)
    u = User(
        id=str(uuid.uuid4()), workspace_id=ws_id,
        email=email or f"u-{uuid.uuid4().hex[:6]}@test.com",
        name="U",
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        role=role, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(u)
    db.flush()
    return u


# ═══════════════════════════════════════════════════════════════════════════
# Test 1 — mv_columns invariant (regressão BHIA3 606×)
# ═══════════════════════════════════════════════════════════════════════════


def test_mv_columns_stay_coherent_after_update_snapshot_item_price(db):
    """Invariante: em qualquer item de snapshot, market_value_native,
    market_value_brl e market_value_usd DEVEM ser coerentes entre si via
    o fx_rate_usd_brl frozen do snapshot pai, e a soma dos itens tem de
    bater com snapshot.total_value_brl / total_value_usd (2 casas).

    Bug de origem: BHIA3 gravado com USD 194k inflado ~606× em prod porque
    UPDATE tocou uma das colunas de mv sem recomputar as outras. Ver
    memória mv_columns_invariant.md.
    """
    period = date(2026, 4, 30)
    seed = _seed_ws(db, ptax_date=period, ptax_rate=Decimal("5.00"))
    ws = seed["ws"]
    now = seed["now"]

    # 1 BRL asset com posição + 1 USD asset com posição.
    petr = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=seed["acc_brl"].id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Petrobras", ticker="PETR4",
        currency=Currency.BRL, current_price=Decimal("30.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    aapl = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=seed["acc_usd"].id,
        asset_class=AssetClass.STOCK, country="US",
        name="Apple", ticker="AAPL",
        currency=Currency.USD, current_price=Decimal("200.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([petr, aapl])
    # Movimentos pra gerar posição.
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=petr.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 10),
        quantity=Decimal("100"), unit_price=Decimal("30.00"),
        gross_amount=Decimal("3000"), net_amount=Decimal("3000"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=aapl.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 10),
        quantity=Decimal("10"), unit_price=Decimal("200.00"),
        gross_amount=Decimal("2000"), net_amount=Decimal("2000"),
        currency=Currency.USD, fx_rate=Decimal("5.0"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()

    r = create_snapshot(db, workspace_id=ws.id, period_end=period,
                       initial_status=SnapshotStatus.IN_REVIEW)
    snap = db.get(PortfolioSnapshot, r.snapshot_id)
    fx = snap.fx_rate_usd_brl
    assert fx == Decimal("5.00"), "PTAX seed foi injetado 5.00"

    # ── (a) Update BRL item price ───────────────────────────────────
    update_snapshot_item_price(
        db, snapshot_id=snap.id, asset_id=petr.id,
        user_id="tester", new_price=Decimal("42.00"),
        value_mode="unit",
    )
    item_petr = db.query(PortfolioSnapshotItem).filter_by(
        snapshot_id=snap.id, asset_id=petr.id,
    ).one()
    # BRL native → mv_brl = mv_native; mv_usd = mv_brl / fx
    assert item_petr.market_value_native == Decimal("100") * Decimal("42.00")
    assert item_petr.market_value_brl == item_petr.market_value_native
    assert item_petr.market_value_usd == item_petr.market_value_brl / fx

    # ── (b) Update USD item price ───────────────────────────────────
    update_snapshot_item_price(
        db, snapshot_id=snap.id, asset_id=aapl.id,
        user_id="tester", new_price=Decimal("250.00"),
        value_mode="unit",
    )
    item_aapl = db.query(PortfolioSnapshotItem).filter_by(
        snapshot_id=snap.id, asset_id=aapl.id,
    ).one()
    # USD native → mv_usd = mv_native; mv_brl = mv_usd * fx
    assert item_aapl.market_value_native == Decimal("10") * Decimal("250.00")
    assert item_aapl.market_value_usd == item_aapl.market_value_native
    assert item_aapl.market_value_brl == item_aapl.market_value_usd * fx

    # ── (c) Soma dos itens bate com total do snapshot ──────────────
    db.refresh(snap)
    items = db.query(PortfolioSnapshotItem).filter_by(snapshot_id=snap.id).all()
    sum_brl = sum((i.market_value_brl or Decimal("0")) for i in items)
    sum_usd = sum((i.market_value_usd or Decimal("0")) for i in items)
    # 2 casas de tolerância — mesma unidade em que total_value_brl é
    # armazenado (Numeric(18, 2)).
    assert round(snap.total_value_brl, 2) == round(sum_brl, 2), (
        f"snapshot.total_value_brl={snap.total_value_brl} não bate "
        f"com sum(items.market_value_brl)={sum_brl}"
    )
    assert round(snap.total_value_usd, 2) == round(sum_usd, 2), (
        f"snapshot.total_value_usd={snap.total_value_usd} não bate "
        f"com sum(items.market_value_usd)={sum_usd}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test 2 — CorporateAction ratio validation via HTTP
# ═══════════════════════════════════════════════════════════════════════════


def _override_get_db(db):
    """Force TestClient a usar o mesmo session do teste (padrão do
    test_bulk_extract.py) — usa `yield` com retorno da mesma sessão."""
    def _gen():
        yield db
    return _gen


def test_corporate_action_endpoint_rejects_bad_ratios_and_accepts_valid(db):
    """Invariante: POST /api/corporate-actions valida a direção do ratio
    conforme a convenção do modelo (SPLIT > 1, GROUPING < 1) e exige
    target_asset_id + target_ratio pra ASSET_CONVERSION.

    Bug de origem: BHIA3 25:1 gravado com ratio invertido em prod —
    agrupamento chegou como ratio=25 (inflando qty 25×) em vez de
    ratio=0.04. Ver commit e comentário em routes/corporate_actions.py
    ("bug herdado do import Notion do BHIA3").
    """
    seed = _seed_ws(db)
    ws = seed["ws"]
    now = seed["now"]
    admin = _mk_user(db, ws.id, role=UserRole.admin,
                     email="ca-admin@test.com", password="pw")
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=seed["acc_brl"].id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Casas Bahia", ticker="BHIA3",
        currency=Currency.BRL, current_price=Decimal("10.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    target = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=seed["acc_brl"].id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Target", ticker="TGT1",
        currency=Currency.BRL, current_price=Decimal("5.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([asset, target])
    db.flush()
    db.commit()

    token = AuthService(db).login("ca-admin@test.com", "pw")
    headers = {"Authorization": f"Bearer {token}"}

    app.dependency_overrides[get_db] = _override_get_db(db)
    try:
        with TestClient(app) as c:
            # (1) SPLIT com ratio <= 1 → 422 ("ratio" no detail)
            r1 = c.post("/api/corporate-actions", json={
                "asset_id": asset.id,
                "event_date": "2026-04-15",
                "event_type": "SPLIT",
                "ratio": "0.5",
            }, headers=headers)
            assert r1.status_code == 422, r1.text
            assert "ratio" in r1.json()["detail"].lower()

            # (2) GROUPING com ratio >= 1 → 422
            r2 = c.post("/api/corporate-actions", json={
                "asset_id": asset.id,
                "event_date": "2026-04-16",
                "event_type": "GROUPING",
                "ratio": "2.0",
            }, headers=headers)
            assert r2.status_code == 422, r2.text
            assert "ratio" in r2.json()["detail"].lower()

            # (3) ASSET_CONVERSION sem target_asset_id → 422
            r3 = c.post("/api/corporate-actions", json={
                "asset_id": asset.id,
                "event_date": "2026-04-17",
                "event_type": "ASSET_CONVERSION",
                "ratio": "1.0",
            }, headers=headers)
            assert r3.status_code == 422, r3.text

            # (4) SPLIT válido (ratio > 1) → 201
            r_ok = c.post("/api/corporate-actions", json={
                "asset_id": asset.id,
                "event_date": "2026-04-18",
                "event_type": "SPLIT",
                "ratio": "2.0",
            }, headers=headers)
            assert r_ok.status_code == 201, r_ok.text
            body = r_ok.json()
            assert body["corporate_action"]["event_type"] == "SPLIT"
            assert Decimal(body["corporate_action"]["ratio"]) == Decimal("2.0")
    finally:
        app.dependency_overrides.clear()

    # Persistiu exatamente 1 CA (só o SPLIT válido).
    persisted = db.query(CorporateAction).filter(
        CorporateAction.asset_id == asset.id,
        CorporateAction.is_active == True,  # noqa: E712
    ).all()
    assert len(persisted) == 1
    assert persisted[0].event_type == CorporateActionType.SPLIT
    assert persisted[0].ratio == Decimal("2.0")


# ═══════════════════════════════════════════════════════════════════════════
# Test 3 — bulk_income out_of_period NÃO entra no snapshot
# ═══════════════════════════════════════════════════════════════════════════


def test_bulk_income_drops_out_of_period_events(db):
    """Invariante: eventos com event_date fora do mês do snapshot alvo
    NÃO entram no apply_plan, NÃO viram Distribution, e o preview reporta
    quantos foram ignorados.

    Bug de origem: commit 38d8195 corrigiu proventos fora do mês entrando
    no snapshot alvo (Avenue XLSX multi-mês tinha eventos de mar/abr/mai
    aplicados no snapshot de maio).
    """
    seed = _seed_ws(db)
    ws = seed["ws"]
    fi_av = seed["fi_av"]
    now = seed["now"]

    # Asset WMT (US) pra bater com um dos eventos (mesmo os in-period têm
    # de ir pra apply_plan pra provar que só os out-of-period são
    # descartados).
    wmt = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=seed["acc_usd"].id,
        asset_class=AssetClass.STOCK, country="US",
        name="Walmart Inc", ticker="WMT",
        currency=Currency.USD, current_price=Decimal("80"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(wmt)
    # Snapshot mai/26 (period_end = último dia calendário).
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 5, 31),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
    )
    db.add(snap)
    db.flush()

    # PTAX das duas datas relevantes (WMT dist in-period e out-of-period).
    for d in (date(2026, 5, 27), date(2026, 4, 27)):
        db.add(PTAXRate(
            id=str(uuid.uuid4()), date=d, rate=Decimal("5.10"),
            source="BCB_SGS", fetched_at=now,
        ))
    db.flush()

    # Job BROKER_INCOME com 1 evento in-period + 1 out-of-period (abr/26).
    payload = {
        "events": [
            {  # dentro do período (mai/26) — deve entrar no apply_plan
                "event_date": "2026-05-27",
                "ticker_raw": "WMT",
                "type": "DIVIDEND",
                "gross_amount": 12.32,
                "tax_amount": 0.0,
                "net_amount": 12.32,
                "currency": "USD",
            },
            {  # FORA do período (abr/26) — deve ser dropado
                "event_date": "2026-04-27",
                "ticker_raw": "WMT",
                "type": "DIVIDEND",
                "gross_amount": 99.99,
                "tax_amount": 0.0,
                "net_amount": 99.99,
                "currency": "USD",
            },
        ]
    }
    # Cria job direto — bypass do LLM/attachment (apenas classificação
    # nos importa).
    job = ExtractionJob(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        snapshot_id=snap.id,
        pendency_id=None,
        institution_id=fi_av.id,
        # attachment_id: precisa NOT NULL, então stub. Não é lido pelo
        # classify — só _apply_bulk_income_to_snapshot precisa se rodar
        # o LLM, o que não fazemos.
        attachment_id=str(uuid.uuid4()),  # fake — só classify é chamado
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        status=ExtractionStatus.EXTRACTED,
        extracted_json=payload,
        created_at=now,
    )
    db.add(job)
    db.flush()

    # ── (a) Classify direto (o entrypoint que decide dentro/fora) ────
    apply_plan, preview, orphan, duplicate, errors = (
        extraction_service._classify_bulk_income(db, job, payload)
    )
    # Só o in-period entrou no plano.
    assert len(apply_plan) == 1
    assert apply_plan[0]["event_date"] == "2026-05-27"
    # O out-of-period NÃO aparece nem em preview, nem em orphan, nem em
    # duplicate — ficou retido no counter interno.
    assert all(row["event_date"] != "2026-04-27" for row in preview)
    assert all(row["event_date"] != "2026-04-27" for row in orphan)
    assert all(row["event_date"] != "2026-04-27" for row in duplicate)
    # E o counter é reportado via `errors` (padrão do serviço:
    # "N evento(s) fora do período ... ignorado(s)").
    assert any("fora do período" in e for e in errors), errors
    assert any("2026-04-27" not in e or "ignorado" in e for e in errors)

    # ── (b) confirm_extraction NÃO cria Distribution pro out-of-period ─
    result = extraction_service.confirm_extraction(
        db, job_id=job.id, user_id=None, user_email="test@test.com",
    )
    assert result.applied_count == 1  # só o in-period
    dists = db.query(Distribution).filter(
        Distribution.workspace_id == ws.id
    ).all()
    assert len(dists) == 1
    assert dists[0].event_date == date(2026, 5, 27)
    # Confirma explicitamente: nenhum Distribution com data em abr/26.
    assert not any(d.event_date == date(2026, 4, 27) for d in dists)


# ═══════════════════════════════════════════════════════════════════════════
# Test 4 — JWT com role stale é reconciliado do DB (deps.get_current_user)
# ═══════════════════════════════════════════════════════════════════════════


def test_jwt_role_reconciled_from_db_on_each_request(db):
    """Invariante: `get_current_user` SEMPRE resolve role/workspace_id
    contra o DB. Sem isso, promoção/rebaixamento fica invisível pra APIs
    até o user logout+login, gerando estado híbrido (UI vê role nova, API
    retorna 403).

    Cenário A — promoção member→admin com token member antigo → GET /users
    retorna 200 (role reconciliada do DB).
    Cenário B — rebaixamento sysadmin→admin com token sysadmin antigo →
    GET /sysadmin/logs/tail retorna 403 (não fica sysadmin fantasma).

    Ver src/numis_geek/api/deps.py:47-53.
    """
    seed = _seed_ws(db)
    ws = seed["ws"]

    # ── Cenário A: promoção ─────────────────────────────────────────
    promoted = _mk_user(db, ws.id, role=UserRole.member,
                        email="promo@test.com", password="pw")
    db.commit()
    # Emite token quando ainda é member.
    token_promo = AuthService(db).login("promo@test.com", "pw")
    # Promove no DB (sem re-login).
    promoted.role = UserRole.admin
    db.commit()

    # ── Cenário B: rebaixamento ─────────────────────────────────────
    demoted = _mk_user(db, None, role=UserRole.sysadmin,
                       email="demo@test.com", password="pw")
    db.commit()
    token_demo = AuthService(db).login("demo@test.com", "pw")
    demoted.role = UserRole.admin
    demoted.workspace_id = ws.id  # rebaixado tem de virar admin de ws
    db.commit()

    app.dependency_overrides[get_db] = _override_get_db(db)
    try:
        with TestClient(app) as c:
            # A — token diz "member", mas DB diz "admin". Endpoint admin+
            # (GET /api/users) deve autorizar.
            r_a = c.get("/api/users", headers={
                "Authorization": f"Bearer {token_promo}",
            })
            assert r_a.status_code == 200, (
                f"promoção member→admin não foi reconciliada: {r_a.status_code} {r_a.text}"
            )

            # B — token diz "sysadmin", DB diz "admin". Endpoint
            # sysadmin-only deve retornar 403.
            r_b = c.get("/api/sysadmin/logs/tail", headers={
                "Authorization": f"Bearer {token_demo}",
            })
            assert r_b.status_code == 403, (
                f"rebaixamento sysadmin→admin não foi reconciliado: "
                f"{r_b.status_code} {r_b.text}"
            )
    finally:
        app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Test 5 — CASH asset com posição zerada vira item no snapshot
# ═══════════════════════════════════════════════════════════════════════════


def test_cash_asset_appears_in_snapshot_with_zero_position(db):
    """Invariante: asset com asset_class=CASH aparece no snapshot mesmo
    com quantity_held=0 e total_invested_brl=0 — CASH representa saldo em
    conta atualizado manualmente por fechamento, sem movements.

    `asset_has_position(pos, asset)` deve retornar True pra CASH sem depender
    de qty ou invested. E `create_snapshot` deve materializar o item.

    Bug de origem: spec 49 hotfix #12 — antes do fix, CASH sumia do snapshot
    porque a guarda `qty == 0` em create_snapshot filtrava fora todos os
    ativos VALUE-puros. Ver memória cash-balance-assets-are-real.
    """
    period = date(2026, 4, 30)
    seed = _seed_ws(db, ptax_date=period, ptax_rate=Decimal("5.10"))
    ws = seed["ws"]
    now = seed["now"]

    cash = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=seed["acc_brl"].id,
        asset_class=AssetClass.CASH, country="BR",
        name="Saldo em Conta XP", ticker=None,
        currency=Currency.BRL, current_price=None,
        price_source=None,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(cash)
    db.flush()

    # Passo 1 — asset_has_position(pos, asset) é True mesmo com pos zerada.
    pos = compute_position(db, cash.id, as_of=period)
    assert pos["quantity_held"] == Decimal("0")
    assert pos["total_invested_brl"] == Decimal("0")
    assert asset_has_position(pos, cash) is True, (
        "CASH sem movements deve ser tratado como posição real (saldo em "
        "conta), não filtrado."
    )
    # E, invariante inverso: helper devolve False pra pos zerada de asset
    # NON-cash (regressão contra alguém remover o branch de CASH).
    non_cash = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=seed["acc_brl"].id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Empty stock", ticker="EMPTY",
        currency=Currency.BRL, current_price=None,
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(non_cash)
    db.flush()
    pos_stock = compute_position(db, non_cash.id, as_of=period)
    assert asset_has_position(pos_stock, non_cash) is False

    # Passo 2 — create_snapshot materializa o item pra CASH.
    r = create_snapshot(
        db, workspace_id=ws.id, period_end=period,
        initial_status=SnapshotStatus.IN_REVIEW,
    )
    items = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == cash.id,
    ).all()
    assert len(items) == 1, (
        "CASH asset com posição zerada NÃO apareceu no snapshot — "
        "regressão do hotfix spec 49 #12."
    )
    item = items[0]
    # Sem current_price nem movements, market_value_brl é 0 ou None
    # (o snapshot herda o mv=None do compute_position). O invariante que
    # protege é o item EXISTIR.
    assert item.market_value_brl in (None, Decimal("0")), (
        f"Esperado mv_brl=0/None, veio {item.market_value_brl}"
    )
    # O asset non-cash zerado NÃO gerou item (confirma que só o branch
    # de CASH salva zeros).
    other_items = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == r.snapshot_id,
        PortfolioSnapshotItem.asset_id == non_cash.id,
    ).count()
    assert other_items == 0


# ═══════════════════════════════════════════════════════════════════════════
# Test 6 — value_mode="total" + qty>1 num asset value-mode NÃO esmaga o total
# ═══════════════════════════════════════════════════════════════════════════


def test_update_snapshot_item_price_total_mode_with_qty_gt1_on_value_mode_asset(db):
    """Invariante: em asset value-mode (FUND, RF, PREV, CASH, FGTS), a
    combinação `value_mode='total'` + `new_quantity=N>1` deve resultar em
    `unit_price=total` (não `total/N`) porque o clamp posterior força
    item.quantity=1, e sem o clamp anterior no divisor o total fica 1/N do
    valor enviado.

    Bug de origem: task 56 (detectado 2026-07-29 escrevendo
    test_snapshots_routes_matrix). Frontend hoje só envia
    `value_mode='unit'` para value-mode, mas nada no backend impede um
    caller externo de mandar `total` — o valor sairia ⅓/¼/⅕ silenciosamente.
    """
    period = date(2026, 4, 30)
    seed = _seed_ws(db, ptax_date=period, ptax_rate=Decimal("5.00"))
    ws = seed["ws"]
    now = seed["now"]

    # Fundo value-mode com 2 aportes (running_qty=2 pós-normalize_valor_qty).
    fund = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=seed["acc_brl"].id,
        asset_class=AssetClass.FUND, country="BR",
        name="Fundo Segurança MP",
        currency=Currency.BRL, current_price=None,
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(fund)
    for i in range(2):
        db.add(AssetMovement(
            id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=fund.id,
            type=AssetMovementType.BUY, event_date=date(2026, 1, 10 + i),
            quantity=Decimal("1"), unit_price=Decimal("200"),
            gross_amount=Decimal("200"), net_amount=Decimal("200"),
            currency=Currency.BRL, fx_rate=Decimal("1"),
            is_active=True, created_at=now, updated_at=now,
        ))
    db.flush()

    r = create_snapshot(db, workspace_id=ws.id, period_end=period,
                       initial_status=SnapshotStatus.IN_REVIEW)
    snap = db.get(PortfolioSnapshot, r.snapshot_id)

    # Payload malicioso do teste: total=1200 mas alegando qty=3.
    update_snapshot_item_price(
        db, snapshot_id=snap.id, asset_id=fund.id,
        user_id="tester", new_price=Decimal("1200"),
        value_mode="total", new_quantity=Decimal("3"),
    )

    item = db.query(PortfolioSnapshotItem).filter_by(
        snapshot_id=snap.id, asset_id=fund.id,
    ).one()
    # Clamp value-mode força qty=1.
    assert item.quantity == Decimal("1"), (
        f"Esperado quantity=1 (clamp value-mode), veio {item.quantity}"
    )
    # unit_price deve manter o total enviado — NÃO dividido por 3.
    assert item.unit_price == Decimal("1200"), (
        f"Bug 56: esperado unit_price=1200, veio {item.unit_price} "
        f"(seria 400 se o divisor pré-clamp não fosse ajustado)."
    )
    # Consequência: mv_native = 1 × 1200 = 1200 (não 400).
    assert item.market_value_native == Decimal("1200"), (
        f"Esperado mv_native=1200, veio {item.market_value_native}"
    )
    assert item.market_value_brl == Decimal("1200"), (
        f"Esperado mv_brl=1200 (asset BRL), veio {item.market_value_brl}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test 7 — mv_columns invariant via apply_recompute_to_snapshot
# ═══════════════════════════════════════════════════════════════════════════


def test_apply_recompute_updates_all_three_mv_columns_and_snapshot_totals(db):
    """Invariante idêntico ao test_1 mas via apply_recompute_to_snapshot:
    quando uma mov retroativa dispara recompute, o item resultante DEVE
    ter os 3 mv_* coerentes via fx_rate frozen do snapshot, E os totais
    do snapshot DEVEM bater com SUM(items).

    Bug de origem: mesma família do BHIA3 606× — se apply_recompute
    esquecer de recomputar todas as 3 colunas mv_* + refresh dos totais
    do snapshot pai, mv_usd fica LIVE (do fx_rate atual) em vez de
    frozen (do snap.fx_rate_usd_brl). Ver memória mv_columns_invariant.md
    e session_state audit 2026-07-05 (task 39 do audit de coerência).
    """
    period = date(2026, 4, 30)
    seed = _seed_ws(db, ptax_date=period, ptax_rate=Decimal("5.00"))
    ws = seed["ws"]
    now = seed["now"]

    aapl = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=seed["acc_usd"].id,
        asset_class=AssetClass.STOCK, country="US",
        name="Apple", ticker="AAPL",
        currency=Currency.USD, current_price=Decimal("200.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(aapl)
    # Compra inicial: 10 shares @ 200 antes do period_end.
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=aapl.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 10),
        quantity=Decimal("10"), unit_price=Decimal("200.00"),
        gross_amount=Decimal("2000"), net_amount=Decimal("2000"),
        currency=Currency.USD, fx_rate=Decimal("5.0"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()

    # Cria snapshot IN_REVIEW — item vai ter qty=10, unit_price=200,
    # mv_native=2000, mv_usd=2000, mv_brl=10000 (fx frozen 5.00).
    r = create_snapshot(db, workspace_id=ws.id, period_end=period,
                       initial_status=SnapshotStatus.IN_REVIEW)
    snap = db.get(PortfolioSnapshot, r.snapshot_id)
    fx = snap.fx_rate_usd_brl
    assert fx == Decimal("5.00"), "PTAX seed foi injetado 5.00"

    # Sanity: item inicial.
    item0 = db.query(PortfolioSnapshotItem).filter_by(
        snapshot_id=snap.id, asset_id=aapl.id,
    ).one()
    assert item0.quantity == Decimal("10")
    assert item0.unit_price == Decimal("200.00")

    # period_end < hoje pode gerar HISTORICAL_PRICE_REQUIRED via
    # _new_item_values (PriceSource.MANUAL → provider retorna None).
    # Limpa pendencies pra permitir o close abaixo — o unit_price já foi
    # travado no item pelo create_snapshot no branch is_today (não é o
    # caso aqui), então preenche manualmente se preciso pra manter
    # invariante do close (SUM(items) == totals).
    from numis_geek.models.portfolio_snapshot import SnapshotPendency
    db.query(SnapshotPendency).filter_by(snapshot_id=snap.id).delete()
    db.flush()
    # Se o item não conseguiu preço histórico, injeta o unit_price frozen
    # manualmente pra simular a resolução da pendency (equivalente ao
    # user editar preço via UI).
    if item0.unit_price is None:
        item0.unit_price = Decimal("200.00")
        item0.market_value_native = item0.quantity * item0.unit_price
        item0.market_value_usd = item0.market_value_native
        item0.market_value_brl = item0.market_value_native * fx
        db.flush()

    # Fecha snapshot pra travar fx_rate frozen (força auto-reopen dentro
    # do apply_recompute — path mais realista do bug retroativo).
    confirm_snapshot(db, snapshot_id=snap.id, user_id="tester",
                     user_email="tester@test.com")
    db.refresh(snap)
    assert snap.status == SnapshotStatus.CLOSED
    assert snap.fx_rate_usd_brl == Decimal("5.00")

    # Movimento retroativo: BUY 5 shares @ 210 com event_date < period_end.
    retro = AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=aapl.id,
        type=AssetMovementType.BUY, event_date=date(2026, 3, 15),
        quantity=Decimal("5"), unit_price=Decimal("210.00"),
        gross_amount=Decimal("1050"), net_amount=Decimal("1050"),
        currency=Currency.USD, fx_rate=Decimal("5.0"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(retro)
    db.flush()

    # Dispara o recompute (path do bug — não passa por update_snapshot_item_price).
    apply_recompute_to_snapshot(
        db,
        snapshot_id=snap.id,
        asset_id=aapl.id,
        trigger_event_type="asset_movement",
        trigger_event_id=retro.id,
        user_id="tester",
        user_email="tester@test.com",
    )

    item = db.query(PortfolioSnapshotItem).filter_by(
        snapshot_id=snap.id, asset_id=aapl.id,
    ).one()
    # Qty soma o retro: 10 + 5 = 15.
    assert item.quantity == Decimal("15"), (
        f"Esperado quantity=15 (10 + 5 retro), veio {item.quantity}"
    )
    # Spec 52: unit_price frozen preservado (não é 210 nem average).
    assert item.unit_price == Decimal("200.00"), (
        f"unit_price frozen deve permanecer 200 (spec 52), veio {item.unit_price}"
    )
    # mv_native = 15 × 200 = 3000.
    assert item.market_value_native == Decimal("15") * Decimal("200.00"), (
        f"Esperado mv_native=3000, veio {item.market_value_native}"
    )
    # USD asset → mv_usd = mv_native.
    assert item.market_value_usd == item.market_value_native, (
        f"USD asset: mv_usd deve == mv_native, veio "
        f"{item.market_value_usd} vs {item.market_value_native}"
    )
    # mv_brl = mv_native × fx FROZEN (5.00) — NÃO fx live/atual.
    assert item.market_value_brl == item.market_value_native * fx, (
        f"mv_brl deve usar fx frozen ({fx}): esperado "
        f"{item.market_value_native * fx}, veio {item.market_value_brl}"
    )
    assert item.market_value_brl == Decimal("15000.00"), (
        f"Esperado mv_brl=15000 (3000 × 5.00), veio {item.market_value_brl}"
    )

    # Totais do snapshot batem com SUM(items) — bug de origem quebrava
    # aqui quando o refresh do total no fim do apply_recompute era omitido.
    db.refresh(snap)
    items = db.query(PortfolioSnapshotItem).filter_by(snapshot_id=snap.id).all()
    sum_brl = sum((i.market_value_brl or Decimal("0") for i in items), Decimal("0"))
    sum_usd = sum((i.market_value_usd or Decimal("0") for i in items), Decimal("0"))
    assert round(snap.total_value_brl, 2) == round(sum_brl, 2), (
        f"snapshot.total_value_brl={snap.total_value_brl} não bate "
        f"com sum(items.market_value_brl)={sum_brl}"
    )
    assert round(snap.total_value_usd, 2) == round(sum_usd, 2), (
        f"snapshot.total_value_usd={snap.total_value_usd} não bate "
        f"com sum(items.market_value_usd)={sum_usd}"
    )
