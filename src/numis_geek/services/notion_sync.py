"""One-way push from Numis-Geek to Notion.

Entry points (one per entity):
- push_asset(db, asset)
- push_asset_movement(db, m)
- push_snapshot(db, snap)
- push_corporate_action(db, ca)

Each:
1. Resolves credentials from IntegrationCredential.
2. If entity.external_id is NULL → create_page; else update_page (with
   conflict detection unless force=True).
3. On success: sets notion_sync_status=SYNCED, notion_last_synced_at=now,
   notion_remote_last_edited_at=page.last_edited_time, clears error.
4. On conflict: notion_sync_status=CONFLICT, does NOT push. Caller's UI must
   show diff and ask user to confirm via /resolve endpoint (force=True).
5. On error: notion_sync_status=ERROR, notion_sync_error=str(e).

Relations (Classe / País / IF / Carteira) are skipped in spec 16 because
resolving them requires another round-trip lookup to auxiliary Notion DBs
that don't exist as local entities. The user can populate them manually
in Notion after the first sync; subsequent updates won't touch the
relation property.

ASSET_CONVERSION corporate actions are skipped (DB IG Eventos doesn't model
conversions). They stay PENDING with a sync_error explaining why.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from numis_geek.integrations.notion import (
    NotionClient,
    NotionError,
    NotionNotFound,
    NotionPage,
    prop_date,
    prop_number,
    prop_relation,
    prop_rich_text,
    prop_select,
    prop_title,
)
from numis_geek.models.asset import Asset
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.corporate_action import CorporateAction, CorporateActionType
from numis_geek.models.external import ExternalSource
from numis_geek.models.integration_credential import (
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.models.notion_sync import NotionSyncStatus
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
)

log = logging.getLogger(__name__)


# ── Credential resolution ────────────────────────────────────────────────────

CREDENTIAL_KEYS = {
    "TOKEN": "NOTION_TOKEN",
    "DB_ATIVOS": "DB_IG_ATIVOS",
    "DB_LANCAMENTO": "DB_IG_LANCAMENTO",
    "DB_APURACAO": "DB_IG_APURACAO",
    "DB_LOTE_APURACAO": "DB_IG_LOTE_APURACAO",
    "DB_EVENTOS": "DB_IG_EVENTOS",
}


class NotionCredentialMissing(RuntimeError):
    pass


def _get_credential(db: Session, key_name: str) -> str:
    row = (
        db.query(IntegrationCredential)
        .filter(
            IntegrationCredential.provider == IntegrationProvider.NOTION,
            IntegrationCredential.key_name == key_name,
            IntegrationCredential.is_active.is_(True),
            IntegrationCredential.workspace_id.is_(None),
        )
        .first()
    )
    if not row:
        raise NotionCredentialMissing(
            f"Missing IntegrationCredential NOTION/{key_name}. "
            "Configure it at /sysadmin/integrations."
        )
    return row.secret_value


def _client(db: Session) -> NotionClient:
    return NotionClient(_get_credential(db, CREDENTIAL_KEYS["TOKEN"]))


# ── Conflict detection ───────────────────────────────────────────────────────


@dataclass
class SyncResult:
    status: NotionSyncStatus
    notion_page_id: str | None
    notion_url: str | None
    error: str | None
    conflict_remote_edited_at: str | None = None


def _detect_conflict(entity, remote_page: NotionPage) -> bool:
    """True if Notion's page has been edited since our last successful sync."""
    saved = getattr(entity, "notion_remote_last_edited_at", None)
    if saved is None:
        return False
    try:
        remote = datetime.fromisoformat(remote_page.last_edited_time.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    saved_utc = saved if saved.tzinfo else saved.replace(tzinfo=timezone.utc)
    return remote > saved_utc


def _mark_synced(entity, page: NotionPage) -> None:
    entity.external_id = page.id
    entity.external_source = ExternalSource.NOTION
    entity.notion_last_synced_at = datetime.now(timezone.utc)
    try:
        entity.notion_remote_last_edited_at = datetime.fromisoformat(
            page.last_edited_time.replace("Z", "+00:00")
        )
    except (ValueError, AttributeError):
        entity.notion_remote_last_edited_at = datetime.now(timezone.utc)
    entity.notion_sync_status = NotionSyncStatus.SYNCED
    entity.notion_sync_error = None


def _mark_error(entity, msg: str) -> None:
    entity.notion_sync_status = NotionSyncStatus.ERROR
    entity.notion_sync_error = msg[:500]


def _mark_skipped(entity, reason: str) -> None:
    """Mark an entity as intentionally not pushed to Notion (e.g. option
    lifecycle movements not modeled in the upstream Notion DB schema). See
    `docs/options-rationale.md` §3.3."""
    entity.notion_sync_status = NotionSyncStatus.SKIPPED
    entity.notion_sync_error = reason[:500]


def _mark_conflict(entity, remote_edited_at: str) -> None:
    entity.notion_sync_status = NotionSyncStatus.CONFLICT
    entity.notion_sync_error = (
        f"Remote page edited at {remote_edited_at}; refusing to overwrite. "
        "Use force_push to override."
    )


# ── Property builders per entity ─────────────────────────────────────────────


def _asset_to_props(asset: Asset) -> dict[str, Any]:
    """Build Notion properties for DB IG Ativos. Relations skipped — user
    populates manually in Notion."""
    notion_type = "Cotado" if asset.ticker else "Não Cotado"
    props = {
        "Ticker": prop_title(asset.ticker or asset.name),
        "Nome do Ativo": prop_rich_text(asset.name),
        "Tipo do Ativo": prop_select(notion_type),
    }
    return props


_MOVEMENT_TYPE_PT = {
    AssetMovementType.BUY: "Compra",
    AssetMovementType.SELL: "Venda",
    AssetMovementType.BONUS: "Bonificação",
    AssetMovementType.SUBSCRIPTION: "Subscrição",
    AssetMovementType.COME_COTAS: "ComeCota",
    AssetMovementType.FULL_REDEMPTION: "Resgate Total",
    # Option lifecycle (Spec 17) — labels mirror UI conventions.
    AssetMovementType.SELL_OPEN: "Venda pra abrir",
    AssetMovementType.BUY_TO_OPEN: "Compra pra abrir",
    AssetMovementType.SELL_TO_CLOSE: "Venda pra fechar",
    AssetMovementType.BUY_TO_CLOSE: "Compra pra fechar",
    AssetMovementType.EXERCISED: "Exercida",
    AssetMovementType.EXPIRED: "Vencida",
}


def _movement_to_props(m: AssetMovement, asset_notion_id: str) -> dict[str, Any]:
    label = f"{_MOVEMENT_TYPE_PT[m.type]} {m.event_date.isoformat()}"
    taxes: Decimal | None = None
    if m.fee is not None or m.tax is not None:
        taxes = (m.fee or Decimal("0")) + (m.tax or Decimal("0"))

    props: dict[str, Any] = {
        "Name": prop_title(label),
        "Tipo Transação": prop_select(_MOVEMENT_TYPE_PT[m.type]),
        "Data Transação": prop_date(m.event_date.isoformat()),
        "Ativo": prop_relation([asset_notion_id]),
    }
    if m.quantity is not None:
        props["Qtde"] = prop_number(float(m.quantity))
    if m.unit_price is not None:
        props["Preço Unit."] = prop_number(float(m.unit_price))
    if taxes is not None:
        props["Taxas"] = prop_number(float(taxes))
    if m.gross_amount is not None and m.type == AssetMovementType.COME_COTAS:
        props["AR Valor"] = prop_number(float(m.gross_amount))
    if m.fx_rate is not None and m.currency.value == "USD":
        props["Cambio do Dia (R$ / 1U$)"] = prop_number(float(m.fx_rate))
    if m.nota_negociacao_number:
        props["Número Nota Negociação"] = prop_rich_text(m.nota_negociacao_number)
    if m.notes:
        props["Comentários"] = prop_rich_text(m.notes)
    return props


def _snapshot_to_props(snap: PortfolioSnapshot) -> dict[str, Any]:
    label = f"{snap.period_end_date.strftime('%Y-%m')} Apuração"
    props: dict[str, Any] = {
        "Name": prop_title(label),
        "Data Apuração": prop_date(snap.period_end_date.isoformat()),
    }
    if snap.fx_rate_usd_brl is not None:
        props["Cambio Dolar/Real"] = prop_number(float(snap.fx_rate_usd_brl))
    return props


def _snapshot_item_to_props(
    item: PortfolioSnapshotItem,
    asset: Asset,
    snap_notion_id: str,
) -> dict[str, Any]:
    label = f"{item.created_at.strftime('%Y%m') if item.created_at else ''} {asset.ticker or asset.name}".strip()
    props: dict[str, Any] = {
        "Name": prop_title(label),
        "Ativo": prop_relation([asset.external_id]) if asset.external_id else prop_relation([]),
        "Lote Apuracao": prop_relation([snap_notion_id]),
    }
    if item.unit_price is not None:
        props["QP Preço Unit. Apurado MC"] = prop_number(float(item.unit_price))
    if item.market_value_native is not None and asset.asset_class.value in ("CASH", "FGTS", "FIXED_INCOME"):
        props["AR Valor"] = prop_number(float(item.market_value_native))
    return props


_CA_TYPE_PT = {
    CorporateActionType.SPLIT: "Split (Desdobramento)",
    CorporateActionType.GROUPING: "Inplit (Agrupamento)",
}


def _corporate_action_to_props(ca: CorporateAction, asset: Asset) -> dict[str, Any]:
    label = f"{asset.ticker or asset.name} {ca.event_date.isoformat()} {_CA_TYPE_PT.get(ca.event_type, ca.event_type.value)}"
    props: dict[str, Any] = {
        "Name": prop_title(label),
        "Data Evento": prop_date(ca.event_date.isoformat()),
        "Tipo Evento": prop_select(_CA_TYPE_PT[ca.event_type]),
        "Proporção:": prop_number(float(ca.ratio)),
        "Ativo": prop_relation([asset.external_id]) if asset.external_id else prop_relation([]),
    }
    if ca.notes:
        props["Comentários"] = prop_rich_text(ca.notes)
    return props


# ── Push primitives ──────────────────────────────────────────────────────────


def _push(
    db: Session,
    entity,
    database_id: str,
    properties: dict[str, Any],
    client: NotionClient,
    force: bool,
) -> SyncResult:
    """Generic create-or-update with conflict detection."""
    try:
        if entity.external_id:
            # Update existing — first check conflict
            if not force:
                try:
                    current = client.retrieve_page(entity.external_id)
                except NotionNotFound:
                    # Local has external_id but Notion lost the page → treat as create
                    entity.external_id = None
                    return _push(db, entity, database_id, properties, client, force)
                if _detect_conflict(entity, current):
                    _mark_conflict(entity, current.last_edited_time)
                    return SyncResult(
                        status=NotionSyncStatus.CONFLICT,
                        notion_page_id=entity.external_id,
                        notion_url=None,
                        error=entity.notion_sync_error,
                        conflict_remote_edited_at=current.last_edited_time,
                    )
            page = client.update_page(entity.external_id, properties)
        else:
            page = client.create_page(database_id, properties)
    except NotionError as e:
        _mark_error(entity, str(e))
        return SyncResult(
            status=NotionSyncStatus.ERROR,
            notion_page_id=entity.external_id,
            notion_url=None,
            error=str(e),
        )

    _mark_synced(entity, page)
    return SyncResult(
        status=NotionSyncStatus.SYNCED,
        notion_page_id=page.id,
        notion_url=page.url,
        error=None,
    )


# ── Entry points ─────────────────────────────────────────────────────────────


def push_asset(
    db: Session, asset: Asset, *, force: bool = False, client: NotionClient | None = None
) -> SyncResult:
    cli = client or _client(db)
    db_id = _get_credential(db, CREDENTIAL_KEYS["DB_ATIVOS"])
    return _push(db, asset, db_id, _asset_to_props(asset), cli, force)


_OPTION_LIFECYCLE_TYPES = frozenset({
    AssetMovementType.SELL_OPEN,
    AssetMovementType.BUY_TO_OPEN,
    AssetMovementType.SELL_TO_CLOSE,
    AssetMovementType.BUY_TO_CLOSE,
    AssetMovementType.EXERCISED,
    AssetMovementType.EXPIRED,
})


def push_asset_movement(
    db: Session, m: AssetMovement, *, force: bool = False, client: NotionClient | None = None
) -> SyncResult:
    # Option lifecycle types aren't representable in the upstream Notion DB
    # schema (which only knows the 6 classic types). See
    # `docs/options-rationale.md` §3.3.
    if m.type in _OPTION_LIFECYCLE_TYPES:
        _mark_skipped(m, "Option-lifecycle movement; not pushed to Notion.")
        return SyncResult(NotionSyncStatus.SKIPPED, None, None, m.notion_sync_error)

    cli = client or _client(db)
    asset = db.get(Asset, m.asset_id)
    if not asset:
        _mark_error(m, f"Asset {m.asset_id} not found.")
        return SyncResult(NotionSyncStatus.ERROR, None, None, m.notion_sync_error)

    # Auto-push asset first if it's not in Notion yet
    if not asset.external_id or asset.notion_sync_status in (
        NotionSyncStatus.PENDING, NotionSyncStatus.ERROR
    ):
        asset_result = push_asset(db, asset, force=force, client=cli)
        if asset_result.status != NotionSyncStatus.SYNCED:
            _mark_error(m, f"Asset push failed: {asset_result.error}")
            return SyncResult(NotionSyncStatus.ERROR, None, None, m.notion_sync_error)

    db_id = _get_credential(db, CREDENTIAL_KEYS["DB_LANCAMENTO"])
    return _push(db, m, db_id, _movement_to_props(m, asset.external_id), cli, force)


def push_snapshot(
    db: Session,
    snap: PortfolioSnapshot,
    *,
    force: bool = False,
    client: NotionClient | None = None,
    include_items: bool = True,
) -> SyncResult:
    cli = client or _client(db)
    db_id = _get_credential(db, CREDENTIAL_KEYS["DB_LOTE_APURACAO"])
    header_result = _push(db, snap, db_id, _snapshot_to_props(snap), cli, force)
    if header_result.status != NotionSyncStatus.SYNCED:
        return header_result

    if include_items and snap.external_id:
        items_db_id = _get_credential(db, CREDENTIAL_KEYS["DB_APURACAO"])
        items = (
            db.query(PortfolioSnapshotItem)
            .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
            .all()
        )
        for item in items:
            asset = db.get(Asset, item.asset_id)
            if not asset:
                continue
            # Asset must exist in Notion first
            if not asset.external_id:
                push_asset(db, asset, force=force, client=cli)
            if not asset.external_id:
                _mark_error(item, "Asset has no Notion page.")
                continue
            _push(
                db, item, items_db_id,
                _snapshot_item_to_props(item, asset, snap.external_id), cli, force,
            )
    return header_result


def push_corporate_action(
    db: Session, ca: CorporateAction, *, force: bool = False, client: NotionClient | None = None
) -> SyncResult:
    if ca.event_type == CorporateActionType.ASSET_CONVERSION:
        _mark_error(ca, "ASSET_CONVERSION is not supported by DB IG Eventos. Skipping.")
        return SyncResult(
            status=NotionSyncStatus.ERROR,
            notion_page_id=None,
            notion_url=None,
            error=ca.notion_sync_error,
        )

    cli = client or _client(db)
    asset = db.get(Asset, ca.asset_id)
    if not asset:
        _mark_error(ca, f"Asset {ca.asset_id} not found.")
        return SyncResult(NotionSyncStatus.ERROR, None, None, ca.notion_sync_error)

    if not asset.external_id:
        push_asset(db, asset, force=force, client=cli)
    if not asset.external_id:
        _mark_error(ca, "Asset has no Notion page (push_asset failed).")
        return SyncResult(NotionSyncStatus.ERROR, None, None, ca.notion_sync_error)

    db_id = _get_credential(db, CREDENTIAL_KEYS["DB_EVENTOS"])
    return _push(db, ca, db_id, _corporate_action_to_props(ca, asset), cli, force)


# ── Bulk helpers ─────────────────────────────────────────────────────────────


def list_pending(db: Session, workspace_id: str | None) -> dict[str, int]:
    """Counts of PENDING/ERROR per entity, scoped to workspace if given."""
    out: dict[str, int] = {}
    for model, key in (
        (Asset, "assets"),
        (AssetMovement, "asset_movements"),
        (PortfolioSnapshot, "snapshots"),
        (CorporateAction, "corporate_actions"),
    ):
        q = db.query(model).filter(
            model.notion_sync_status.in_(
                [NotionSyncStatus.PENDING, NotionSyncStatus.ERROR]
            )
        )
        if workspace_id and hasattr(model, "workspace_id"):
            q = q.filter(model.workspace_id == workspace_id)
        out[key] = q.count()
    return out
