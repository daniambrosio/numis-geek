"""Portfolio snapshot service — fotografia of positions at a period_end.

Spec 14 originally; Spec 35 extends with lifecycle (SCHEDULED/IN_REVIEW/
CLOSED), pendency detection per source, confirm/reopen flows, and audit.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.models.account import Account
from numis_geek.models.asset import Asset, PriceSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PendencyAction,
    PendencyReason,
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotPendency,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.services.audit import AuditService
from numis_geek.services.fx import FxRateNotFound, fx_rate_on
from numis_geek.services.positions import asset_has_position, compute_position
from numis_geek.services.price_freshness import (
    AUTOMATED_SOURCES,
    PriceTier,
    freshness_tier,
)


@dataclass
class SnapshotResult:
    snapshot_id: str
    period_end_date: date
    items_count: int
    total_value_brl: Decimal
    total_value_usd: Decimal
    fx_rate_usd_brl: Decimal | None
    status: SnapshotStatus = SnapshotStatus.CLOSED
    pendencies_count: int = 0
    pendency_ids: list[str] = field(default_factory=list)


# Spec 51 — Retroactive Event Reconciliation. AffectedSnapshot describes
# the per-snapshot impact of a (proposed or already-saved) retroactive
# event for a given asset.
@dataclass
class AffectedSnapshot:
    snapshot_id: str
    period_end_date: date
    ym: str                          # "YYYY-MM"
    status: SnapshotStatus
    has_item: bool                   # already has an item for this asset?
    old_quantity: Decimal
    new_quantity: Decimal
    old_market_value_brl: Decimal | None
    new_market_value_brl: Decimal | None
    old_total_invested_brl: Decimal | None
    new_total_invested_brl: Decimal | None
    # 2026-06-09: patrimônio total atual do snapshot, pra UI calcular
    # "antes → depois" do fechamento inteiro (não só do item).
    snapshot_total_value_brl: Decimal = Decimal("0")


# ── Pendency detection ──────────────────────────────────────────────────────


def _is_avenue_generic(db: Session, asset: Asset) -> bool:
    """UPLOAD heuristic: assets that arrive without ticker via Avenue's
    generic 'rendimento' feed are flagged as upload-required.

    Cheap path: ticker IS NULL + asset's account is at an institution
    whose short_name is 'Avenue'. Refine as we learn the data better.
    """
    if asset.ticker:
        return False
    acc = db.get(Account, asset.account_id) if asset.account_id else None
    if not acc:
        return False
    fi = db.get(FinancialInstitution, acc.financial_institution_id)
    if not fi:
        return False
    return (fi.short_name or "").lower() == "avenue"


def detect_pendencies(
    db: Session,
    asset: Asset,
    *,
    period_end: date,
    now: datetime | None = None,
) -> tuple[PendencyReason, PendencyAction, str] | None:
    """Inspect a single asset and return (reason, action, detail) when it
    blocks closing the snapshot. None when the asset is fine.

    Rules (spec 35 §2.2):
    - NULL / no source            → skip (no pendency)
    - MANUAL                      → MANUAL_SOURCE (or UPLOAD_REQUIRED via heuristic)
    - Automated source + price OK (tier FRESH or STALE) → no pendency
    - Automated source + tier OLD → STALE_PRICE
    - Automated source + never refreshed (price_updated_at IS NULL) → API_FAILED
    """
    source = asset.price_source
    if source is None:
        return None

    if source == PriceSource.MANUAL:
        if _is_avenue_generic(db, asset):
            return (
                PendencyReason.UPLOAD_REQUIRED,
                PendencyAction.UPLOAD_FILE,
                "Avenue generic feed — upload extract",
            )
        return (
            PendencyReason.MANUAL_SOURCE,
            PendencyAction.EDIT_PRICE,
            "Manual price source — needs user edit",
        )

    if source in AUTOMATED_SOURCES:
        if asset.price_updated_at is None:
            return (
                PendencyReason.API_FAILED,
                PendencyAction.RETRY_API,
                f"{source.value}: never refreshed",
            )
        tier = freshness_tier(asset.price_updated_at, source, now=now)
        if tier == PriceTier.OLD:
            return (
                PendencyReason.STALE_PRICE,
                PendencyAction.RETRY_API,
                f"{source.value}: price older than 7 days at {period_end}",
            )

    return None


# ── Helper para item NOVO em snapshot (Spec 52) ─────────────────────────────


def _new_item_values(
    snap: PortfolioSnapshot,
    asset: Asset,
    pos: dict,
    *,
    now: datetime,
) -> tuple[
    Decimal | None,        # unit_price
    Decimal | None,        # market_value_native
    Decimal | None,        # market_value_brl
    Decimal | None,        # market_value_usd
    SnapshotPendency | None,  # pendency a persistir (ou None)
]:
    """Spec 52 — decide unit_price + market_values pra um item NOVO sem
    sobrescrever preço frozen com LIVE.

    Regra:
    - Se `snap.period_end_date == today`: usa `pos["current_price"]` —
      é o caso "primeira captura". Asset.current_price representa o
      preço de hoje, que é o period_end_price.
    - Caso contrário: `unit_price=None` + `SnapshotPendency`
      HISTORICAL_PRICE_REQUIRED + EDIT_PRICE. Spec 53 vai eliminar a
      pendency tentando primeiro `historical_price.fetch_on`.

    Caller persiste o `PortfolioSnapshotItem` + (opcional) pendency.
    """
    is_today = snap.period_end_date == date.today()
    qty = pos.get("quantity_held") or Decimal("0")

    if is_today:
        unit_price = pos.get("current_price")
        mv_native = pos.get("current_value")
        mv_brl = pos.get("current_value_brl")
        mv_usd: Decimal | None = None
        if mv_brl is not None:
            fx = snap.fx_rate_usd_brl
            ccy = asset.currency.value
            if ccy == "USD":
                mv_usd = mv_native
            elif ccy == "BRL" and fx and fx > 0:
                mv_usd = mv_brl / fx
        return unit_price, mv_native, mv_brl, mv_usd, None

    # period_end no passado — não sabemos preço histórico.
    pen = SnapshotPendency(
        id=str(uuid.uuid4()),
        snapshot_id=snap.id,
        asset_id=asset.id,
        reason=PendencyReason.HISTORICAL_PRICE_REQUIRED,
        action_type=PendencyAction.EDIT_PRICE,
        detail=(
            f"Ativo adicionado retroativamente — informe o preço de "
            f"fechamento de {snap.period_end_date.isoformat()}."
        ),
        created_at=now,
    )
    # qty pode ser != 0 (mov retroativa cravou posição), mas sem
    # unit_price não temos market_value. Caller persiste qty.
    _ = qty  # silencia lint
    return None, None, None, None, pen


# ── Snapshot creation ───────────────────────────────────────────────────────


def _delete_snapshot_cascade(db: Session, snap: PortfolioSnapshot) -> None:
    db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == snap.id
    ).delete()
    db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == snap.id
    ).delete()
    db.delete(snap)
    db.flush()


def create_snapshot(
    db: Session,
    *,
    workspace_id: str,
    period_end: date,
    user_id: str | None = None,
    source: SnapshotSource = SnapshotSource.MANUAL,
    initial_status: SnapshotStatus = SnapshotStatus.CLOSED,
    replace_if_exists: bool = True,
    force_reopen: bool = False,
    now: datetime | None = None,
) -> SnapshotResult:
    """Create or replace a snapshot for workspace at period_end.

    `initial_status` is the desired status when no pendencies exist.
    Detected pendencies will downgrade the status to IN_REVIEW
    automatically.

    `force_reopen=True` is required to overwrite an existing CLOSED
    snapshot — protects against accidental data loss.
    """
    existing = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.period_end_date == period_end,
        )
        .first()
    )
    if existing:
        if not replace_if_exists:
            raise ValueError(f"Snapshot already exists for {period_end}")
        if existing.status == SnapshotStatus.CLOSED and not force_reopen:
            raise ValueError(
                f"Snapshot for {period_end} is CLOSED. Pass force_reopen=True to overwrite."
            )
        _delete_snapshot_cascade(db, existing)

    try:
        fx = fx_rate_on(db, period_end)
    except FxRateNotFound:
        fx = None

    now = now or datetime.now(timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        period_end_date=period_end,
        fx_rate_usd_brl=fx,
        total_value_brl=Decimal("0"),
        total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"),
        total_received_brl=Decimal("0"),
        source=source,
        status=initial_status,
        is_active=True,
        created_at=now, updated_at=now,
        created_by=user_id, updated_by=user_id,
    )
    db.add(snap)
    db.flush()

    total_brl = Decimal("0")
    total_usd = Decimal("0")
    total_inv_brl = Decimal("0")
    total_rec_brl = Decimal("0")
    items_count = 0
    pendency_ids: list[str] = []

    assets = (
        db.query(Asset)
        .filter(
            Asset.workspace_id == workspace_id,
            Asset.is_active == True,  # noqa: E712
        )
        .all()
    )

    for asset in assets:
        pos = compute_position(db, asset.id, as_of=period_end)
        if not asset_has_position(pos, asset):
            continue
        qty = pos["quantity_held"]

        mv_native = pos["current_value"]
        mv_brl = pos["current_value_brl"]
        mv_usd: Decimal | None = None

        currency = asset.currency.value
        if mv_brl is not None:
            if currency == "USD":
                mv_usd = mv_native
            elif currency == "BRL" and fx is not None and fx > 0:
                mv_usd = mv_brl / fx

        db.add(PortfolioSnapshotItem(
            id=str(uuid.uuid4()),
            snapshot_id=snap.id,
            asset_id=asset.id,
            quantity=qty,
            unit_price=pos["current_price"],
            market_value_native=mv_native,
            market_value_brl=mv_brl,
            market_value_usd=mv_usd,
            average_cost_brl=pos["average_cost_brl"],
            total_invested_brl=pos["total_invested_brl"],
            created_at=now,
        ))
        items_count += 1

        if mv_brl is not None:
            total_brl += mv_brl
        if mv_usd is not None:
            total_usd += mv_usd
        total_inv_brl += pos["total_invested_brl"]
        total_rec_brl += pos["total_received_brl"]

        # Detect pendency for this asset at this snapshot.
        det = detect_pendencies(db, asset, period_end=period_end, now=now)
        if det is not None:
            reason, action, detail = det
            pen = SnapshotPendency(
                id=str(uuid.uuid4()),
                snapshot_id=snap.id,
                asset_id=asset.id,
                reason=reason,
                action_type=action,
                detail=detail,
                created_at=now,
            )
            db.add(pen)
            db.flush()
            pendency_ids.append(pen.id)

    snap.total_value_brl = total_brl
    snap.total_value_usd = total_usd
    snap.total_invested_brl = total_inv_brl
    snap.total_received_brl = total_rec_brl

    # Downgrade to IN_REVIEW if there are open pendencies and the caller asked for CLOSED.
    if pendency_ids and initial_status == SnapshotStatus.CLOSED:
        snap.status = SnapshotStatus.IN_REVIEW
    elif snap.status == SnapshotStatus.CLOSED:
        # Cleanly closed — stamp closed_at/by.
        snap.closed_at = now
        snap.closed_by = user_id

    db.flush()

    return SnapshotResult(
        snapshot_id=snap.id,
        period_end_date=period_end,
        items_count=items_count,
        total_value_brl=total_brl,
        total_value_usd=total_usd,
        fx_rate_usd_brl=fx,
        status=snap.status,
        pendencies_count=len(pendency_ids),
        pendency_ids=pendency_ids,
    )


# ── Lifecycle transitions ───────────────────────────────────────────────────


class PendencyOpenError(RuntimeError):
    """Raised by confirm_snapshot when at least one pendency is unresolved."""


def confirm_snapshot(
    db: Session,
    *,
    snapshot_id: str,
    user_id: str | None,
    user_email: str | None = None,
) -> PortfolioSnapshot:
    """Close a snapshot. Refuses if any pendency is unresolved.

    Recomputes totals from the persisted items (prices may have moved
    after creation via PATCH /assets/{id}/price or refresh).
    """
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    open_pendencies = (
        db.query(SnapshotPendency)
        .filter(
            SnapshotPendency.snapshot_id == snap.id,
            SnapshotPendency.resolved_at.is_(None),
        )
        .count()
    )
    if open_pendencies > 0:
        raise PendencyOpenError(
            f"Cannot confirm: {open_pendencies} open pendency(ies)"
        )

    # Recompute totals from items (prices/items may have changed via
    # resolution/sync/edit since create_snapshot).
    items = (
        db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
        .all()
    )
    total_brl = sum((i.market_value_brl or Decimal("0") for i in items), Decimal("0"))
    total_usd = sum((i.market_value_usd or Decimal("0") for i in items), Decimal("0"))
    # Bug 4 fix (2026-06-09): total_invested_brl ficava stale no header se
    # items eram adicionados/removidos/editados depois do create_snapshot —
    # rendendo Ganho/Perda absurdo no Dashboard. Recompute aqui pra
    # garantir consistência items ↔ header.
    total_invested_brl = sum(
        (i.total_invested_brl or Decimal("0") for i in items), Decimal("0")
    )
    snap.total_value_brl = total_brl
    snap.total_value_usd = total_usd
    snap.total_invested_brl = total_invested_brl

    now = datetime.now(timezone.utc)
    snap.status = SnapshotStatus.CLOSED
    snap.closed_at = now
    snap.closed_by = user_id
    db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.confirm",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot",
        resource_id=snap.id,
        details={
            "period_end_date": snap.period_end_date.isoformat(),
            "total_value_brl": str(total_brl),
        },
    )
    return snap


def reopen_snapshot(
    db: Session,
    *,
    snapshot_id: str,
    user_id: str | None,
    user_email: str | None = None,
    reason: str,
    now: datetime | None = None,
) -> PortfolioSnapshot:
    """Reopen any snapshot — moves to IN_REVIEW and re-detects pendencies.

    Reopening an older snapshot does NOT cascade-recompute later
    snapshots. The user accepts the historical drift consciously.
    """
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    now = now or datetime.now(timezone.utc)

    # 2026-06-09 incident: o reopen anterior apagava TODAS as pendencies,
    # inclusive as resolvidas (= trabalho manual do user). Quando um
    # lançamento retroativo dispara auto-reopen pra recomputar UM item,
    # o usuário perdia o status "resolvido" de dezenas de outros ativos.
    #
    # Comportamento atual: preservar pendencies resolvidas (resolved_at
    # IS NOT NULL). Só dropar as não-resolvidas pra re-detectar. O loop
    # de re-detect abaixo já pula assets com pendency existente
    # (resolvida ou não), então não duplica.
    db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == snap.id,
        SnapshotPendency.resolved_at.is_(None),
    ).delete()

    # Spec 49 hotfix #12 — add items for assets that should be in the
    # snapshot but aren't (typically VALUE-mode assets that were excluded
    # by the previous `if qty == 0` guard in create_snapshot). Existing
    # items are left untouched — snapshot items remain frozen by design.
    items_added = _sync_missing_value_mode_items(db, snap, now)
    if items_added:
        db.flush()

    # Re-detect based on current asset state (now including any items we
    # just added above).
    items = (
        db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
        .all()
    )
    pendency_ids: list[str] = []
    for it in items:
        asset = db.get(Asset, it.asset_id)
        if asset is None:
            continue
        # Spec 52 — pula assets que já têm pendency (caso típico:
        # HISTORICAL_PRICE_REQUIRED criada pelo
        # `_sync_missing_value_mode_items` acima).
        already = (
            db.query(SnapshotPendency)
            .filter(
                SnapshotPendency.snapshot_id == snap.id,
                SnapshotPendency.asset_id == asset.id,
            )
            .first()
        )
        if already is not None:
            continue
        # 2026-06-09 incident 2: items que JÁ TÊM preço/valor frozen estão
        # implicitamente resolvidos — não importa de onde veio (manual
        # entry, NOTION_BACKFILL, recompute). detect_pendencies só olha
        # pra asset.price_source (que sempre é MANUAL pra fundo/imóvel/
        # previdência), e reabrir um snapshot backfilleado criava
        # dezenas de pendencies fantasmas que o user precisava redigitar.
        if it.unit_price is not None or it.market_value_brl is not None:
            continue
        det = detect_pendencies(db, asset, period_end=snap.period_end_date, now=now)
        if det is None:
            continue
        r, a, d = det
        pen = SnapshotPendency(
            id=str(uuid.uuid4()),
            snapshot_id=snap.id, asset_id=asset.id,
            reason=r, action_type=a, detail=d, created_at=now,
        )
        db.add(pen)
        pendency_ids.append(pen.id)

    snap.status = SnapshotStatus.IN_REVIEW
    snap.closed_at = None
    snap.closed_by = None

    # 2026-07-05 audit finding — reopen adiciona items via
    # _sync_missing_value_mode_items mas antes deixava snap.total_* stale
    # até o próximo confirm/edit/resolve. Regenera pra manter invariante
    # header == Σ items durante toda a janela IN_REVIEW.
    all_items = (
        db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
        .all()
    )
    snap.total_value_brl = sum(
        (i.market_value_brl or Decimal("0") for i in all_items), Decimal("0"),
    )
    snap.total_value_usd = sum(
        (i.market_value_usd or Decimal("0") for i in all_items), Decimal("0"),
    )
    snap.total_invested_brl = sum(
        (i.total_invested_brl or Decimal("0") for i in all_items), Decimal("0"),
    )
    db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.reopen",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot",
        resource_id=snap.id,
        details={
            "period_end_date": snap.period_end_date.isoformat(),
            "reason": reason,
            "pendencies_recreated": len(pendency_ids),
            "items_added": items_added,
        },
    )
    return snap


# ── Pendency resolution ─────────────────────────────────────────────────────


_UNIT_PRICE_CLASSES = {
    "STOCK", "REIT", "ETF", "OPTION", "CRYPTO",
}


def _default_value_mode_for(asset: Asset | None) -> str:
    """Per-asset_class heuristic for what the user typed.

    - STOCK/REIT/ETF/OPTION/CRYPTO: tradeable on an exchange. User naturally
      types the per-share price (e.g. PETR4 R$ 38.50).
    - Everything else (FIXED_INCOME, FUND, REAL_ESTATE, VEHICLE,
      PRIVATE_PENSION, CASH, OTHER): user reads a TOTAL value off a
      statement (e.g. Tesouro SELIC 2029 R$ 124.215,29 over 6,51 cotas).
      The applier converts to unit_price = total / quantity so the snapshot
      item's market_value = total when re-multiplied.
    """
    if asset is None or asset.asset_class is None:
        return "unit"
    return "unit" if asset.asset_class.value in _UNIT_PRICE_CLASSES else "total"


def resolve_pendency(
    db: Session,
    *,
    pendency_id: str,
    user_id: str | None,
    user_email: str | None = None,
    new_price: Decimal | None = None,
    value_mode: str | None = None,
    file_id: str | None = None,
    note: str | None = None,
) -> SnapshotPendency:
    """Mark a pendency as resolved.

    If `new_price`: update Asset.current_price + the corresponding
    PortfolioSnapshotItem for this snapshot. If `file_id`: attach to the
    pendency note (LLM extraction is a future spec).

    `value_mode`:
    - "unit"   — `new_price` is the per-unit price (stocks, ETFs, etc.)
    - "total"  — `new_price` is the consolidated market value; divide by
                 the position's quantity to derive unit_price
    - None     — auto-detect from asset_class (Spec 49 hotfix #9). Without
                 this, callers like the per-pendency `POST /resolve`
                 endpoint pass `value_mode=None` and the system multiplies
                 a total-shaped input by quantity, blowing market_value up
                 (e.g. SELIC 2029: 124k × 6.51 = R$ 808k).
    """
    pen = db.get(SnapshotPendency, pendency_id)
    if pen is None:
        raise ValueError(f"Pendency {pendency_id} not found")

    snap = db.get(PortfolioSnapshot, pen.snapshot_id)
    asset = db.get(Asset, pen.asset_id)
    now = datetime.now(timezone.utc)

    if new_price is not None and asset is not None:
        # Spec 49 hotfix #9 — auto-detect or honor explicit mode. When
        # mode is "total", divide by the position's quantity so that
        # market_value = qty × unit_price = total (correct invariant).
        effective_mode = value_mode or _default_value_mode_for(asset)
        if effective_mode == "total":
            # Mesmo fix da update_snapshot_item_price: preferir item.quantity
            # (frozen truth) sobre compute_position (que soma qty=1 × N em modo
            # valor pós-normalize_valor_qty).
            existing = (
                db.query(PortfolioSnapshotItem)
                .filter(
                    PortfolioSnapshotItem.snapshot_id == pen.snapshot_id,
                    PortfolioSnapshotItem.asset_id == pen.asset_id,
                )
                .first()
            )
            if existing and existing.quantity and existing.quantity > 0:
                qty = existing.quantity
            else:
                position = compute_position(db, pen.asset_id, as_of=snap.period_end_date) if snap else {}
                qty = position.get("quantity_held") or Decimal("0")
            if qty and qty > 0:
                new_price = new_price / qty
        asset.current_price = new_price
        asset.price_updated_at = now
        item = (
            db.query(PortfolioSnapshotItem)
            .filter(
                PortfolioSnapshotItem.snapshot_id == pen.snapshot_id,
                PortfolioSnapshotItem.asset_id == pen.asset_id,
            )
            .first()
        )
        if item is None:
            # Spec 49 hotfix #5 — create the missing item so the asset shows
            # up in the snapshot's frozen positions table. compute_position
            # gives us the cumulative quantity at period_end; fallback to 1
            # when zero (typical previdência / no-movement asset).
            position = compute_position(db, pen.asset_id, as_of=snap.period_end_date) if snap else {}
            qty = position.get("quantity_held") or Decimal("0")
            if qty == 0:
                qty = Decimal("1")
            item = PortfolioSnapshotItem(
                id=str(uuid.uuid4()),
                snapshot_id=pen.snapshot_id,
                asset_id=pen.asset_id,
                quantity=qty,
                average_cost_brl=position.get("average_cost_brl"),
                total_invested_brl=position.get("total_invested_brl"),
            )
            db.add(item)
        item.unit_price = new_price
        if item.quantity is not None:
            # Modo cotado (qty>0): mv = qty × unit_price (que já foi
            # dividido por qty acima quando mode='total').
            # Modo VALOR (qty=0): unit_price É o market_value total
            # — multiplicar daria 0. Bug visto em 2026-06-06 com
            # Previdência (XP Corp Light/Trend Pós-Fixado).
            if item.quantity > 0:
                mv_native = item.quantity * new_price
            else:
                mv_native = new_price
            item.market_value_native = mv_native
            # Recompute BRL/USD using snapshot fx_rate.
            ccy = asset.currency.value if asset else "BRL"
            fx = snap.fx_rate_usd_brl if snap else None
            if ccy == "BRL":
                item.market_value_brl = mv_native
                if fx and fx > 0:
                    item.market_value_usd = mv_native / fx
            elif ccy == "USD":
                item.market_value_usd = mv_native
                if fx and fx > 0:
                    item.market_value_brl = mv_native * fx

    pen.resolved_at = now
    pen.resolved_by = user_id
    pen.resolution_note = note
    db.flush()

    # Refresh snapshot totals from items so the UI doesn't show stale headers.
    if snap is not None:
        items = (
            db.query(PortfolioSnapshotItem)
            .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
            .all()
        )
        snap.total_value_brl = sum(
            (i.market_value_brl or Decimal("0") for i in items), Decimal("0")
        )
        snap.total_value_usd = sum(
            (i.market_value_usd or Decimal("0") for i in items), Decimal("0")
        )
        snap.total_invested_brl = sum(
            (i.total_invested_brl or Decimal("0") for i in items), Decimal("0")
        )
        db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.pendency.resolve",
        workspace_id=snap.workspace_id if snap else None,
        user_id=user_id,
        resource_type="pendency",
        resource_id=pen.id,
        details={
            "snapshot_id": pen.snapshot_id,
            "asset_id": pen.asset_id,
            "reason": pen.reason.value,
            "new_price": str(new_price) if new_price is not None else None,
            "file_id": file_id,
            "note": note,
        },
    )
    return pen


def update_snapshot_item_price(
    db: Session,
    *,
    snapshot_id: str,
    asset_id: str,
    user_id: str | None,
    user_email: str | None = None,
    new_price: Decimal,
    value_mode: str | None = None,
    note: str | None = None,
    new_quantity: Decimal | None = None,
) -> PortfolioSnapshotItem:
    """Spec 49 hotfix #10 — inline edit a snapshot item's price.

    Used by the UI when the user clicks an asset row in Posições Congeladas
    to fix a wrong value WITHOUT going through the pendency flow (the
    pendency may already be resolved, or never existed for this asset).

    Applies the same unit-vs-total conversion as `resolve_pendency` so all
    paths stay aligned. Only allowed on IN_REVIEW snapshots — CLOSED ones
    must be reopened first.

    `new_quantity`: override do qty herdado do movement history. Persiste no
    item.quantity sem tocar em movements — para casos onde o extrato do
    custodiante mostra qty diferente do calculado (bonificação/come-cotas
    não capturada em lançamento). Se None, qty existente é preservado.
    """
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    if snap.status == SnapshotStatus.CLOSED:
        raise ValueError(
            "Snapshot CLOSED — reopen it before editing items.",
        )
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ValueError(f"Asset {asset_id} not found")

    effective_mode = value_mode or _default_value_mode_for(asset)
    stored_price = Decimal(str(new_price))
    if effective_mode == "total":
        # Bug 2026-07-02: pós-normalize_valor_qty todo movement em modo valor
        # tem qty=1, então compute_position devolve N (número de aportes) em
        # vez de um qty semântico. Dividir por N esmaga o total (369,22 → 184,61
        # em Fundo Segurança MP com 2 aportes). Fix: preferir item.quantity,
        # que é o qty FROZEN do snapshot (=1 pra modo valor, =shares reais pra
        # cotado). compute_position vira só fallback pra item que ainda não
        # existe.
        if new_quantity is not None and new_quantity > 0:
            qty = new_quantity
        else:
            existing = (
                db.query(PortfolioSnapshotItem)
                .filter(
                    PortfolioSnapshotItem.snapshot_id == snapshot_id,
                    PortfolioSnapshotItem.asset_id == asset_id,
                )
                .first()
            )
            if existing and existing.quantity and existing.quantity > 0:
                qty = existing.quantity
            else:
                position = compute_position(db, asset_id, as_of=snap.period_end_date)
                qty = position.get("quantity_held") or Decimal("0")
        if qty and qty > 0:
            stored_price = stored_price / qty

    now = datetime.now(timezone.utc)
    asset.current_price = stored_price
    asset.price_updated_at = now

    item = (
        db.query(PortfolioSnapshotItem)
        .filter(
            PortfolioSnapshotItem.snapshot_id == snapshot_id,
            PortfolioSnapshotItem.asset_id == asset_id,
        )
        .first()
    )
    if item is None:
        position = compute_position(db, asset_id, as_of=snap.period_end_date)
        qty = position.get("quantity_held") or Decimal("1")
        if qty == 0:
            qty = Decimal("1")
        item = PortfolioSnapshotItem(
            id=str(uuid.uuid4()),
            snapshot_id=snapshot_id, asset_id=asset_id,
            quantity=qty,
            average_cost_brl=position.get("average_cost_brl"),
            total_invested_brl=position.get("total_invested_brl"),
        )
        db.add(item)
    if new_quantity is not None and new_quantity > 0:
        item.quantity = new_quantity
    item.unit_price = stored_price
    if item.quantity is not None:
        # Mesma regra do resolve_pendency: qty>0 multiplica, qty=0
        # (modo VALOR) usa stored_price direto como market_value total.
        if item.quantity > 0:
            mv_native = item.quantity * stored_price
        else:
            mv_native = stored_price
        item.market_value_native = mv_native
        ccy = asset.currency.value
        fx = snap.fx_rate_usd_brl
        if ccy == "BRL":
            item.market_value_brl = mv_native
            if fx and fx > 0:
                item.market_value_usd = mv_native / fx
        elif ccy == "USD":
            item.market_value_usd = mv_native
            if fx and fx > 0:
                item.market_value_brl = mv_native * fx

    # Se houver pendência aberta pra esse (snapshot, asset), marca como
    # resolvida — assim o mesmo fluxo de edição cobre os 2 caminhos
    # (Editar na seção Pendências e Editar na seção Posições Congeladas).
    open_pen = (
        db.query(SnapshotPendency)
        .filter(
            SnapshotPendency.snapshot_id == snapshot_id,
            SnapshotPendency.asset_id == asset_id,
            SnapshotPendency.resolved_at.is_(None),
        )
        .first()
    )
    if open_pen is not None:
        open_pen.resolved_at = now
        open_pen.resolved_by = user_id
        open_pen.resolution_note = note

    db.flush()

    # Refresh snapshot totals.
    items = (
        db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snapshot_id)
        .all()
    )
    snap.total_value_brl = sum(
        (i.market_value_brl or Decimal("0") for i in items), Decimal("0"),
    )
    snap.total_value_usd = sum(
        (i.market_value_usd or Decimal("0") for i in items), Decimal("0"),
    )
    snap.total_invested_brl = sum(
        (i.total_invested_brl or Decimal("0") for i in items), Decimal("0"),
    )
    db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.item.edit",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot_item",
        resource_id=item.id,
        details={
            "snapshot_id": snapshot_id,
            "asset_id": asset_id,
            "asset_name": asset.name,
            "asset_class": asset.asset_class.value if asset.asset_class else None,
            "input_price": str(new_price),
            "effective_mode": effective_mode,
            "stored_unit_price": str(stored_price),
            "market_value_brl": str(item.market_value_brl) if item.market_value_brl else None,
            "note": note,
        },
    )
    return item


def add_snapshot_item(
    db: Session,
    *,
    snapshot_id: str,
    asset_id: str,
    user_id: str | None,
    user_email: str | None = None,
) -> PortfolioSnapshotItem:
    """Spec 49 hotfix #12 — manually add a single asset to an IN_REVIEW
    snapshot. Used when the user knows an asset belongs to a period but
    the auto-pipeline didn't include it (no movements before period end
    yet, or any other quirky scenario).

    Validates: snapshot is IN_REVIEW, asset belongs to same workspace,
    asset is active, asset isn't already in the snapshot. Initial item
    reflects current `compute_position` state — user adjusts via the
    edit modal afterwards.
    """
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    if snap.status == SnapshotStatus.CLOSED:
        raise ValueError(
            "Snapshot CLOSED — reopen it before adding items.",
        )
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ValueError(f"Asset {asset_id} not found")
    if asset.workspace_id != snap.workspace_id:
        raise ValueError("Asset belongs to another workspace.")
    if not asset.is_active:
        raise ValueError("Asset is inactive — reactivate it first.")
    existing = (
        db.query(PortfolioSnapshotItem)
        .filter(
            PortfolioSnapshotItem.snapshot_id == snapshot_id,
            PortfolioSnapshotItem.asset_id == asset_id,
        )
        .first()
    )
    if existing is not None:
        raise ValueError("Asset already in snapshot.")

    now = datetime.now(timezone.utc)
    pos = compute_position(db, asset_id, as_of=snap.period_end_date)
    # Spec 52 — não escreve LIVE price em snapshot antigo.
    unit_price, mv_native, mv_brl, mv_usd, hist_pen = _new_item_values(
        snap, asset, pos, now=now,
    )
    item = PortfolioSnapshotItem(
        id=str(uuid.uuid4()),
        snapshot_id=snapshot_id,
        asset_id=asset_id,
        quantity=pos["quantity_held"] or Decimal("0"),
        unit_price=unit_price,
        market_value_native=mv_native,
        market_value_brl=mv_brl,
        market_value_usd=mv_usd,
        average_cost_brl=pos["average_cost_brl"],
        total_invested_brl=pos["total_invested_brl"],
        created_at=now,
    )
    db.add(item)
    if hist_pen is not None:
        db.add(hist_pen)
    db.flush()

    det = detect_pendencies(db, asset, period_end=snap.period_end_date, now=now)
    if det is not None:
        already_pending = (
            db.query(SnapshotPendency)
            .filter(
                SnapshotPendency.snapshot_id == snapshot_id,
                SnapshotPendency.asset_id == asset_id,
            )
            .first()
        )
        if already_pending is None:
            r, a, d = det
            db.add(SnapshotPendency(
                id=str(uuid.uuid4()),
                snapshot_id=snapshot_id, asset_id=asset_id,
                reason=r, action_type=a, detail=d, created_at=now,
            ))
            db.flush()

    # 2026-07-05 audit finding — regenera snap.total_* pra manter invariante
    # header == Σ items no IN_REVIEW; um item recém-adicionado carrega
    # total_invested_brl>0 sempre e mv_brl frozen em today-snapshots.
    all_items = (
        db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snapshot_id)
        .all()
    )
    snap.total_value_brl = sum(
        (i.market_value_brl or Decimal("0") for i in all_items), Decimal("0"),
    )
    snap.total_value_usd = sum(
        (i.market_value_usd or Decimal("0") for i in all_items), Decimal("0"),
    )
    snap.total_invested_brl = sum(
        (i.total_invested_brl or Decimal("0") for i in all_items), Decimal("0"),
    )
    db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.item.add",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot_item",
        resource_id=item.id,
        details={
            "snapshot_id": snapshot_id,
            "asset_id": asset_id,
            "asset_name": asset.name,
            "asset_class": asset.asset_class.value if asset.asset_class else None,
        },
    )
    return item


def _sync_missing_value_mode_items(
    db: Session,
    snap: PortfolioSnapshot,
    now: datetime,
) -> int:
    """Add `PortfolioSnapshotItem` rows for any active workspace asset
    that has a position at `snap.period_end_date` but isn't yet in the
    snapshot. Returns the number of items added.

    Used by `reopen_snapshot` and by `sync_snapshot_items` (public
    endpoint for IN_REVIEW snapshots that the user can't reopen)."""
    existing_asset_ids = {
        it.asset_id for it in db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snap.id).all()
    }
    workspace_assets = (
        db.query(Asset)
        .filter(
            Asset.workspace_id == snap.workspace_id,
            Asset.is_active == True,  # noqa: E712
        )
        .all()
    )
    items_added = 0
    for asset in workspace_assets:
        if asset.id in existing_asset_ids:
            continue
        pos = compute_position(db, asset.id, as_of=snap.period_end_date)
        if not asset_has_position(pos, asset):
            continue
        # Spec 52 — não escreve LIVE price em snapshot antigo.
        unit_price, mv_native, mv_brl, mv_usd, hist_pen = _new_item_values(
            snap, asset, pos, now=now,
        )
        db.add(PortfolioSnapshotItem(
            id=str(uuid.uuid4()),
            snapshot_id=snap.id,
            asset_id=asset.id,
            quantity=pos["quantity_held"],
            unit_price=unit_price,
            market_value_native=mv_native,
            market_value_brl=mv_brl,
            market_value_usd=mv_usd,
            average_cost_brl=pos["average_cost_brl"],
            total_invested_brl=pos["total_invested_brl"],
            created_at=now,
        ))
        if hist_pen is not None:
            db.add(hist_pen)
        items_added += 1
    return items_added


def sync_snapshot_items(
    db: Session,
    *,
    snapshot_id: str,
    user_id: str | None,
    user_email: str | None = None,
) -> dict:
    """Spec 49 hotfix #12 — public sync endpoint for IN_REVIEW snapshots.

    Adds missing items for assets that should be in the snapshot but
    aren't (typically VALUE-mode assets from the historical bug). Then
    re-detects pendencies for the NEW items only. Existing items and
    their pendencies are untouched (frozen by design).

    Refuses on CLOSED snapshots — user must reopen first."""
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    if snap.status == SnapshotStatus.CLOSED:
        raise ValueError(
            "Snapshot CLOSED — reopen it before syncing missing items.",
        )

    now = datetime.now(timezone.utc)
    items_added = _sync_missing_value_mode_items(db, snap, now)

    # Re-detect pendencies ONLY for newly-added items.
    pendency_ids: list[str] = []
    if items_added:
        db.flush()
        new_items = (
            db.query(PortfolioSnapshotItem)
            .filter(
                PortfolioSnapshotItem.snapshot_id == snap.id,
                PortfolioSnapshotItem.created_at == now,
            )
            .all()
        )
        for it in new_items:
            asset = db.get(Asset, it.asset_id)
            if asset is None:
                continue
            existing = (
                db.query(SnapshotPendency)
                .filter(
                    SnapshotPendency.snapshot_id == snap.id,
                    SnapshotPendency.asset_id == asset.id,
                )
                .first()
            )
            if existing is not None:
                continue
            # Mesmo gate de reopen: item com preço/valor frozen está
            # implicitamente resolvido — não criar pendency fantasma.
            if it.unit_price is not None or it.market_value_brl is not None:
                continue
            det = detect_pendencies(db, asset, period_end=snap.period_end_date, now=now)
            if det is None:
                continue
            r, a, d = det
            pen = SnapshotPendency(
                id=str(uuid.uuid4()),
                snapshot_id=snap.id, asset_id=asset.id,
                reason=r, action_type=a, detail=d, created_at=now,
            )
            db.add(pen)
            pendency_ids.append(pen.id)
        db.flush()

        # 2026-07-05 audit finding — regenera header pra manter invariante
        # snap.total_* == Σ items durante IN_REVIEW; um item recém-adicionado
        # já pode ter market_value_brl frozen (today-snapshot) e deixaria
        # header stale.
        all_items = (
            db.query(PortfolioSnapshotItem)
            .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
            .all()
        )
        snap.total_value_brl = sum(
            (i.market_value_brl or Decimal("0") for i in all_items), Decimal("0"),
        )
        snap.total_value_usd = sum(
            (i.market_value_usd or Decimal("0") for i in all_items), Decimal("0"),
        )
        snap.total_invested_brl = sum(
            (i.total_invested_brl or Decimal("0") for i in all_items), Decimal("0"),
        )
        db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.sync_items",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot",
        resource_id=snap.id,
        details={
            "period_end_date": snap.period_end_date.isoformat(),
            "items_added": items_added,
            "pendencies_added": len(pendency_ids),
        },
    )
    return {
        "items_added": items_added,
        "pendencies_added": len(pendency_ids),
    }


# ── Spec 51 — Retroactive Event Reconciliation ────────────────────────────


def _abs_diff(a: Decimal | None, b: Decimal | None) -> Decimal:
    """Absolute diff treating None as 0. Pequenas variações de
    arredondamento (sub-cent) NÃO devem disparar prompts — usamos
    tolerância de R$ 0,005 / 1e-8 cota."""
    av = a if a is not None else Decimal("0")
    bv = b if b is not None else Decimal("0")
    return abs(av - bv)


_QTY_TOLERANCE = Decimal("1e-8")
_MONEY_TOLERANCE = Decimal("0.005")


def find_affected_snapshots(
    db: Session,
    *,
    workspace_id: str,
    asset_id: str,
    earliest_event_date: date,
) -> list[AffectedSnapshot]:
    """Spec 51 — lista snapshots cujos items do ativo seriam alterados
    se o sistema recomputasse a posição agora, comparado ao que está
    frozen no item atual.

    Inclui só snapshots com `period_end_date >= earliest_event_date`
    (eventos anteriores ao primeiro snapshot relevante não afetam
    nada). Filtra mudanças sub-tolerância pra evitar prompts por ruído
    de arredondamento."""
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id:
        return []

    snaps = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.period_end_date >= earliest_event_date,
        )
        .order_by(PortfolioSnapshot.period_end_date.asc())
        .all()
    )

    out: list[AffectedSnapshot] = []
    for snap in snaps:
        existing = (
            db.query(PortfolioSnapshotItem)
            .filter(
                PortfolioSnapshotItem.snapshot_id == snap.id,
                PortfolioSnapshotItem.asset_id == asset_id,
            )
            .first()
        )
        old_qty = existing.quantity if existing else Decimal("0")
        old_mv_brl = existing.market_value_brl if existing else None
        old_inv = existing.total_invested_brl if existing else None

        pos = compute_position(db, asset_id, as_of=snap.period_end_date)
        # Se a posição recalculada não justifica o ativo no snapshot e
        # não há item, não tem nada pra reportar.
        if not asset_has_position(pos, asset) and existing is None:
            continue

        new_qty = pos["quantity_held"] or Decimal("0")
        # Spec 52 — preço FROZEN do item existente, não LIVE
        # (asset.current_price). Pra item novo em snapshot antigo o
        # preview mostra mv None (vai virar pendency manual). Em
        # snapshot de hoje (primeira captura) pode usar current_price.
        currency = asset.currency.value
        if existing is not None:
            preview_unit_price = existing.unit_price
        elif snap.period_end_date == date.today():
            preview_unit_price = pos["current_price"]
        else:
            preview_unit_price = None
        new_mv_native: Decimal | None = None
        new_mv_brl: Decimal | None = None
        if preview_unit_price is not None and new_qty != 0:
            new_mv_native = new_qty * preview_unit_price
            fx_snap = snap.fx_rate_usd_brl
            if currency == "BRL":
                new_mv_brl = new_mv_native
            elif currency == "USD" and fx_snap and fx_snap > 0:
                new_mv_brl = new_mv_native * fx_snap

        new_inv = pos["total_invested_brl"]

        qty_changed = _abs_diff(old_qty, new_qty) > _QTY_TOLERANCE
        mv_changed = _abs_diff(old_mv_brl, new_mv_brl) > _MONEY_TOLERANCE
        inv_changed = _abs_diff(old_inv, new_inv) > _MONEY_TOLERANCE

        if not (qty_changed or mv_changed or inv_changed):
            continue

        out.append(AffectedSnapshot(
            snapshot_id=snap.id,
            period_end_date=snap.period_end_date,
            ym=snap.period_end_date.strftime("%Y-%m"),
            status=snap.status,
            has_item=existing is not None,
            old_quantity=old_qty,
            new_quantity=new_qty,
            old_market_value_brl=old_mv_brl,
            new_market_value_brl=new_mv_brl,
            old_total_invested_brl=old_inv,
            new_total_invested_brl=new_inv,
            snapshot_total_value_brl=snap.total_value_brl or Decimal("0"),
        ))

    return out


def apply_recompute_to_snapshot(
    db: Session,
    *,
    snapshot_id: str,
    asset_id: str,
    trigger_event_type: str,
    trigger_event_id: str,
    user_id: str | None,
    user_email: str | None = None,
) -> PortfolioSnapshotItem:
    """Spec 51 — recomputa um item de snapshot usando o estado atual de
    movimentos + corp actions, **respeitando o fx_rate frozen do
    snapshot**. Se o snapshot estiver CLOSED, faz auto-reopen com
    reason rastreável.

    Audit log inclui delta antes/depois e referência ao evento gerador."""
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ValueError(f"Asset {asset_id} not found")
    if asset.workspace_id != snap.workspace_id:
        raise ValueError("Asset belongs to another workspace.")

    auto_reopened = False
    if snap.status == SnapshotStatus.CLOSED:
        reopen_snapshot(
            db,
            snapshot_id=snapshot_id,
            user_id=user_id,
            user_email=user_email,
            reason=f"recompute por {trigger_event_type} {trigger_event_id}",
        )
        auto_reopened = True
        # Reload after reopen (status changed to IN_REVIEW).
        snap = db.get(PortfolioSnapshot, snapshot_id)

    existing = (
        db.query(PortfolioSnapshotItem)
        .filter(
            PortfolioSnapshotItem.snapshot_id == snapshot_id,
            PortfolioSnapshotItem.asset_id == asset_id,
        )
        .first()
    )
    before = {
        "quantity": str(existing.quantity) if existing else "0",
        "unit_price": str(existing.unit_price) if existing and existing.unit_price is not None else None,
        "market_value_brl": str(existing.market_value_brl) if existing and existing.market_value_brl is not None else None,
        "market_value_usd": str(existing.market_value_usd) if existing and existing.market_value_usd is not None else None,
        "total_invested_brl": str(existing.total_invested_brl) if existing and existing.total_invested_brl is not None else None,
    }

    now = datetime.now(timezone.utc)
    pos = compute_position(db, asset_id, as_of=snap.period_end_date)
    currency = asset.currency.value
    new_qty = pos["quantity_held"] or Decimal("0")

    if existing is None:
        if not asset_has_position(pos, asset):
            # Nothing to do — recompute would still produce an empty item.
            raise ValueError(
                "Asset has no position at period_end — nothing to recompute.",
            )
        # Spec 52 — item NOVO: helper decide preço (current_price se
        # period_end == hoje, senão pendency HISTORICAL_PRICE_REQUIRED).
        unit_price, mv_native, mv_brl, mv_usd, hist_pen = _new_item_values(
            snap, asset, pos, now=now,
        )
        existing = PortfolioSnapshotItem(
            id=str(uuid.uuid4()),
            snapshot_id=snapshot_id,
            asset_id=asset_id,
            quantity=new_qty,
            unit_price=unit_price,
            market_value_native=mv_native,
            market_value_brl=mv_brl,
            market_value_usd=mv_usd,
            average_cost_brl=pos["average_cost_brl"],
            total_invested_brl=pos["total_invested_brl"],
            created_at=now,
        )
        db.add(existing)
        if hist_pen is not None:
            # Dedup contra pendency pré-existente do mesmo (snap, asset)
            # — improvável aqui (item era novo), mas defensivo.
            already = (
                db.query(SnapshotPendency)
                .filter(
                    SnapshotPendency.snapshot_id == snapshot_id,
                    SnapshotPendency.asset_id == asset_id,
                )
                .first()
            )
            if already is None:
                db.add(hist_pen)
    else:
        # Spec 52 — item EXISTENTE: preserva unit_price frozen. Só qty,
        # average_cost e total_invested recalculam. market_value deriva
        # do unit_price preservado × new_qty (e fx FROZEN do snapshot).
        existing.quantity = new_qty
        existing.average_cost_brl = pos["average_cost_brl"]
        existing.total_invested_brl = pos["total_invested_brl"]
        if existing.unit_price is not None and new_qty != 0:
            mv_native = new_qty * existing.unit_price
            existing.market_value_native = mv_native
            fx_snap = snap.fx_rate_usd_brl
            if currency == "BRL":
                existing.market_value_brl = mv_native
                existing.market_value_usd = (
                    mv_native / fx_snap if fx_snap and fx_snap > 0 else None
                )
            elif currency == "USD":
                existing.market_value_usd = mv_native
                existing.market_value_brl = (
                    mv_native * fx_snap if fx_snap and fx_snap > 0 else None
                )
        else:
            # Sem preço frozen ou qty zerada — limpa market_value.
            existing.market_value_native = None
            existing.market_value_brl = None
            existing.market_value_usd = None

    db.flush()

    # Refresh snapshot totals.
    items = (
        db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snapshot_id)
        .all()
    )
    snap.total_value_brl = sum(
        (i.market_value_brl or Decimal("0") for i in items), Decimal("0"),
    )
    snap.total_value_usd = sum(
        (i.market_value_usd or Decimal("0") for i in items), Decimal("0"),
    )
    # 2026-07-05 audit finding — recompute do item preservava
    # snap.total_invested_brl frozen do momento de create_snapshot, que
    # ficava R$590k+ divergente da soma real após lançamentos retroativos.
    # Regenera a partir dos items pra garantir invariante header == Σ.
    snap.total_invested_brl = sum(
        (i.total_invested_brl or Decimal("0") for i in items), Decimal("0"),
    )
    db.flush()

    after = {
        "quantity": str(existing.quantity),
        "unit_price": str(existing.unit_price) if existing.unit_price is not None else None,
        "market_value_brl": str(existing.market_value_brl) if existing.market_value_brl is not None else None,
        "market_value_usd": str(existing.market_value_usd) if existing.market_value_usd is not None else None,
        "total_invested_brl": str(existing.total_invested_brl) if existing.total_invested_brl is not None else None,
    }

    # 2026-06-09 — auto-close depois do recompute quando não sobrou
    # nenhuma pendency aberta. Antes o snapshot ficava em IN_REVIEW
    # mesmo sem nada pra resolver, forçando o user a clicar "Confirmar"
    # toda vez que digitava um lançamento retroativo. Esse re-confirm
    # silencioso só vale quando o reopen foi automático nesta mesma
    # call — não interfere com o reopen manual (user explicit).
    auto_reclosed = False
    if auto_reopened:
        open_pendencies = (
            db.query(SnapshotPendency)
            .filter(
                SnapshotPendency.snapshot_id == snapshot_id,
                SnapshotPendency.resolved_at.is_(None),
            )
            .count()
        )
        if open_pendencies == 0:
            snap.status = SnapshotStatus.CLOSED
            snap.closed_at = now
            snap.closed_by = user_id
            db.flush()
            auto_reclosed = True

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.item.recompute",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot_item",
        resource_id=existing.id,
        details={
            "snapshot_id": snapshot_id,
            "asset_id": asset_id,
            "asset_name": asset.name,
            "trigger_event_type": trigger_event_type,
            "trigger_event_id": trigger_event_id,
            "auto_reopened": auto_reopened,
            "auto_reclosed": auto_reclosed,
            "before": before,
            "after": after,
        },
    )
    return existing


def apply_skip_recompute(
    db: Session,
    *,
    snapshot_id: str,
    asset_id: str,
    trigger_event_type: str,
    trigger_event_id: str,
    reason: str,
    user_id: str | None,
    user_email: str | None = None,
) -> None:
    """Spec 51 — registra no audit_log que o usuário decidiu manter a
    divergência detectada (drift consciente). Sem mutação de dados."""
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ValueError(f"Asset {asset_id} not found")
    if asset.workspace_id != snap.workspace_id:
        raise ValueError("Asset belongs to another workspace.")

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.recompute.skipped",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot_item",
        resource_id=f"{snapshot_id}:{asset_id}",
        details={
            "snapshot_id": snapshot_id,
            "asset_id": asset_id,
            "asset_name": asset.name,
            "period_end_date": snap.period_end_date.isoformat(),
            "trigger_event_type": trigger_event_type,
            "trigger_event_id": trigger_event_id,
            "reason": reason,
        },
    )


def delete_snapshot_item(
    db: Session,
    *,
    snapshot_id: str,
    asset_id: str,
    user_id: str | None,
    user_email: str | None = None,
) -> None:
    """Spec 49 hotfix #11 — remove an asset from a frozen snapshot.

    Use when a retroactive movement (e.g. a FULL_REDEMPTION dated in
    the snapshot period but registered after the snapshot was created)
    means an asset shouldn't appear in the period at all. Drops the
    item, drops any pendency for that asset, and refreshes snapshot
    totals. Only allowed on IN_REVIEW snapshots.
    """
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")
    if snap.status == SnapshotStatus.CLOSED:
        raise ValueError(
            "Snapshot CLOSED — reopen it before removing items.",
        )
    item = (
        db.query(PortfolioSnapshotItem)
        .filter(
            PortfolioSnapshotItem.snapshot_id == snapshot_id,
            PortfolioSnapshotItem.asset_id == asset_id,
        )
        .first()
    )
    if item is None:
        raise ValueError("Snapshot item not found")

    asset = db.get(Asset, asset_id)
    asset_name = asset.name if asset else asset_id
    asset_class = asset.asset_class.value if asset and asset.asset_class else None
    item_market_value_brl = (
        str(item.market_value_brl) if item.market_value_brl is not None else None
    )
    db.delete(item)

    db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == snapshot_id,
        SnapshotPendency.asset_id == asset_id,
    ).delete()

    db.flush()

    items = (
        db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snapshot_id)
        .all()
    )
    snap.total_value_brl = sum(
        (i.market_value_brl or Decimal("0") for i in items), Decimal("0"),
    )
    snap.total_value_usd = sum(
        (i.market_value_usd or Decimal("0") for i in items), Decimal("0"),
    )
    snap.total_invested_brl = sum(
        (i.total_invested_brl or Decimal("0") for i in items), Decimal("0"),
    )
    db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.item.delete",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot_item",
        resource_id=f"{snapshot_id}:{asset_id}",
        details={
            "snapshot_id": snapshot_id,
            "asset_id": asset_id,
            "asset_name": asset_name,
            "asset_class": asset_class,
            "deleted_market_value_brl": item_market_value_brl,
        },
    )


def retry_pendency_api(
    db: Session,
    *,
    pendency_id: str,
    user_id: str | None,
    user_email: str | None = None,
) -> SnapshotPendency:
    """Re-run the price refresh adapter for an API_FAILED/STALE_PRICE
    pendency. If the refresh succeeds and the price tier becomes
    FRESH/STALE, marks the pendency resolved automatically.
    """
    from numis_geek.services.price_update import refresh_one

    pen = db.get(SnapshotPendency, pendency_id)
    if pen is None:
        raise ValueError(f"Pendency {pendency_id} not found")
    asset = db.get(Asset, pen.asset_id)
    if asset is None:
        raise ValueError(f"Asset {pen.asset_id} not found")

    if pen.action_type != PendencyAction.RETRY_API:
        raise ValueError(
            f"Pendency {pendency_id} is not RETRY_API (got {pen.action_type.value})"
        )

    # Spec 52 — refresh_one chama o adapter LIVE (preço de hoje). Em
    # snapshot antigo isso corrompe o histórico. Spec 53 vai substituir
    # por historical_price.fetch_on; até lá, bloqueia e direciona o
    # user pro fluxo EDIT_PRICE.
    snap = db.get(PortfolioSnapshot, pen.snapshot_id)
    if snap is not None and snap.period_end_date != date.today():
        raise ValueError(
            "Snapshot antigo — API retorna preço de hoje, não do period_end. "
            "Preencha o preço manualmente."
        )

    result = refresh_one(db, asset, user_email=user_email or "system")
    now = datetime.now(timezone.utc)

    if result.status == "ok":
        snap = db.get(PortfolioSnapshot, pen.snapshot_id)
        # Re-evaluate pendency.
        det = detect_pendencies(
            db, asset, period_end=snap.period_end_date if snap else asset.price_updated_at.date(),
            now=now,
        )
        if det is None:
            pen.resolved_at = now
            pen.resolved_by = user_id
            pen.resolution_note = f"API refresh ok: {result.new_price}"
            # Also bump the item price.
            if snap is not None:
                item = (
                    db.query(PortfolioSnapshotItem)
                    .filter(
                        PortfolioSnapshotItem.snapshot_id == snap.id,
                        PortfolioSnapshotItem.asset_id == asset.id,
                    )
                    .first()
                )
                if item is not None and result.new_price is not None:
                    item.unit_price = result.new_price
                    if item.quantity is not None:
                        mv_native = item.quantity * result.new_price
                        item.market_value_native = mv_native
                        ccy = asset.currency.value
                        fx = snap.fx_rate_usd_brl
                        if ccy == "BRL":
                            item.market_value_brl = mv_native
                            if fx and fx > 0:
                                item.market_value_usd = mv_native / fx
                        elif ccy == "USD":
                            item.market_value_usd = mv_native
                            if fx and fx > 0:
                                item.market_value_brl = mv_native * fx
        else:
            pen.detail = f"API refresh succeeded but pendency persists: {det[2]}"
    else:
        pen.detail = f"API refresh {result.status}: {result.error}"

    db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.pendency.retry_api",
        workspace_id=db.get(PortfolioSnapshot, pen.snapshot_id).workspace_id
            if pen.snapshot_id else None,
        user_id=user_id,
        resource_type="pendency",
        resource_id=pen.id,
        details={
            "asset_id": asset.id,
            "ticker": asset.ticker,
            "status": result.status,
            "old_price": str(result.old_price) if result.old_price is not None else None,
            "new_price": str(result.new_price) if result.new_price is not None else None,
            "error": result.error,
        },
    )
    return pen


def list_snapshots(db: Session, workspace_id: str) -> list[PortfolioSnapshot]:
    return (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.is_active == True,  # noqa: E712
        )
        .order_by(PortfolioSnapshot.period_end_date.desc())
        .all()
    )


def list_pendencies(db: Session, snapshot_id: str) -> list[SnapshotPendency]:
    return (
        db.query(SnapshotPendency)
        .filter(SnapshotPendency.snapshot_id == snapshot_id)
        .order_by(SnapshotPendency.created_at.asc())
        .all()
    )
