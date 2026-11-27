"""Spec 85 — ARCA: classificação dos ativos, resumo atual × meta e
simulador de aporte.

- `derive_arca(asset)` — regra automática por classe/indexador/país/moeda.
- `resolve_arca(asset)` — override manual (colunas em `asset`) ou a regra.
- `arca_summary(...)` — valor, meta, banda, renda 12m, ataque × defesa.
- `contribution_plan(...)` — distribui um aporte começando pela letra mais
  atrasada; só sugere venda quando a letra fica acima da banda.

Valor de mercado vem do último fechamento ativo (mesma fonte do
`portfolio_summary`). Percentuais das letras usam como denominador só os
ativos classificados em uma das 4 letras — OUT_OF_SCOPE e não classificados
ficam fora e aparecem à parte.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from numis_geek.models.arca import (
    ARCA_LETTERS,
    ARCA_PARENT,
    ARCA_ROLE,
    ArcaCategory,
    ArcaSubcategory,
)
from numis_geek.models.asset import Asset, AssetClass, FixedIncomeIndexer
from numis_geek.models.asset_fundamentals import AssetFundamentals
from numis_geek.models.distribution import Distribution
from numis_geek.models.portfolio_snapshot import PortfolioSnapshot, PortfolioSnapshotItem
from numis_geek.models.target_allocation import TargetAllocation, TargetAllocationDimension
from numis_geek.services.arca_rules import (
    fii_subcategory,
    sector_hint_from_payload,
    stock_subcategory,
)
from numis_geek.services.audit import AuditService
from numis_geek.services.portfolio_summary import _net_amount_brl_expr
from numis_geek.services.target_allocation import DEFAULT_ARCA_MAX, DEFAULT_ARCA_MIN

ZERO = Decimal("0")
CENT = Decimal("0.01")

# BDR negociado na B3: 4 letras + 32/33/34/35/39 (ex.: AAPL34).
_BDR_RE = re.compile(r"^[A-Z]{4}3[23459]$")


# ── Classificação ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArcaClass:
    category: ArcaCategory | None
    subcategory: ArcaSubcategory | None
    source: str  # "manual" | "derived" | "unmapped"
    note: str = ""  # por que a regra automática escolheu isso


def _is_usd(asset: Asset) -> bool:
    cur = asset.currency.value if hasattr(asset.currency, "value") else asset.currency
    return cur == "USD"


def derive_arca(
    asset: Asset, sector_hint: str | None = None
) -> tuple[ArcaCategory | None, ArcaSubcategory | None]:
    """Regra automática (tabela da spec 85). (None, None) = sem regra —
    precisa de classificação manual."""
    cat, sub, _ = derive_arca_detail(asset, sector_hint)
    return cat, sub


def derive_arca_detail(
    asset: Asset, sector_hint: str | None = None
) -> tuple[ArcaCategory | None, ArcaSubcategory | None, str]:
    cat, sub = _derive_letter(asset)
    note = "classe/indexador/país" if cat else ""
    if sub is None and cat == ArcaCategory.EQUITY_BR:
        sub, note = stock_subcategory(asset.ticker, asset.name, sector_hint)
    elif sub is None and cat == ArcaCategory.REAL_ESTATE:
        sub, note = fii_subcategory(asset.ticker, asset.name, sector_hint)
    return cat, sub, note


def _derive_letter(asset: Asset) -> tuple[ArcaCategory | None, ArcaSubcategory | None]:
    cls = asset.asset_class
    country = (asset.country or "").upper()
    ticker = (asset.ticker or "").upper().strip()

    if cls == AssetClass.STOCK:
        if country == "BR" and not _BDR_RE.match(ticker) and not _is_usd(asset):
            return ArcaCategory.EQUITY_BR, None
        return ArcaCategory.GLOBAL, ArcaSubcategory.GL_EQUITY
    if cls == AssetClass.REIT:
        if country == "BR" and not _is_usd(asset):
            return ArcaCategory.REAL_ESTATE, None
        return ArcaCategory.GLOBAL, ArcaSubcategory.GL_REIT
    if cls == AssetClass.FIXED_INCOME:
        fi = asset.fixed_income
        indexer = fi.indexer if fi else None
        if _is_usd(asset) or indexer == FixedIncomeIndexer.USD:
            return ArcaCategory.GLOBAL, ArcaSubcategory.GL_FIXED_INCOME
        sub = {
            FixedIncomeIndexer.CDI: ArcaSubcategory.CASH_POST_FIXED,
            FixedIncomeIndexer.SELIC: ArcaSubcategory.CASH_POST_FIXED,
            FixedIncomeIndexer.PREFIXED: ArcaSubcategory.CASH_PRE_FIXED,
            FixedIncomeIndexer.IPCA: ArcaSubcategory.CASH_INFLATION,
        }.get(indexer)  # type: ignore[arg-type]
        return ArcaCategory.CASH, sub
    if cls == AssetClass.CRYPTO:
        return ArcaCategory.GLOBAL, ArcaSubcategory.GL_CRYPTO
    if cls == AssetClass.CASH:
        if _is_usd(asset):
            return ArcaCategory.GLOBAL, ArcaSubcategory.GL_FIXED_INCOME
        return ArcaCategory.CASH, ArcaSubcategory.CASH_POST_FIXED
    if cls == AssetClass.ETF:
        if country != "BR" or _is_usd(asset):
            return ArcaCategory.GLOBAL, ArcaSubcategory.GL_EQUITY
        return None, None  # ETF BR: BOVA11, IVVB11, GOLD11… só o user sabe
    if cls in (AssetClass.REAL_ESTATE, AssetClass.VEHICLE, AssetClass.FGTS):
        return ArcaCategory.OUT_OF_SCOPE, None
    # FUND, PRIVATE_PENSION, OPTION
    return None, None


def resolve_arca(asset: Asset, sector_hint: str | None = None) -> ArcaClass:
    d_cat, d_sub, note = derive_arca_detail(asset, sector_hint)
    o_cat = ArcaCategory(asset.arca_category) if asset.arca_category else None
    o_sub = ArcaSubcategory(asset.arca_subcategory) if asset.arca_subcategory else None

    if o_cat is None and o_sub is None:
        if d_cat is None:
            return ArcaClass(None, None, "unmapped")
        return ArcaClass(d_cat, d_sub, "derived", note)

    cat = o_cat or (ARCA_PARENT[o_sub] if o_sub else d_cat)
    if o_sub is not None and ARCA_PARENT[o_sub] == cat:
        sub = o_sub
    elif cat == d_cat:
        sub = d_sub
    else:
        sub = None
    if cat == ArcaCategory.OUT_OF_SCOPE:
        sub = None
    return ArcaClass(cat, sub, "manual", note if sub == d_sub and cat == d_cat else "")


class ArcaClassificationError(ValueError):
    pass


def set_classification(
    db: Session,
    asset: Asset,
    category: str | None,
    subcategory: str | None,
    *,
    user_email: str,
    user_id: str | None,
) -> None:
    """Grava (ou limpa, com None/None) o override. Caller commita."""
    cat = ArcaCategory(category) if category else None
    sub = ArcaSubcategory(subcategory) if subcategory else None
    if sub is not None:
        if cat is None:
            cat = ARCA_PARENT[sub]
        elif ARCA_PARENT[sub] != cat:
            raise ArcaClassificationError(
                f"Subcategoria {sub.value} não pertence a {cat.value}."
            )
    if cat == ArcaCategory.OUT_OF_SCOPE and sub is not None:
        raise ArcaClassificationError("OUT_OF_SCOPE não tem subcategoria.")
    before = {"category": asset.arca_category, "subcategory": asset.arca_subcategory}
    asset.arca_category = cat.value if cat else None
    asset.arca_subcategory = sub.value if sub else None
    asset.updated_by = user_id
    db.flush()
    AuditService(db).log(
        user_email=user_email,
        action="asset.arca_classification",
        workspace_id=asset.workspace_id,
        user_id=user_id,
        resource_type="asset",
        resource_id=asset.id,
        details={
            "before": before,
            "after": {"category": asset.arca_category, "subcategory": asset.arca_subcategory},
        },
    )


# ── Dados de base ────────────────────────────────────────────────────────


def _latest_snapshot(db: Session, workspace_id: str) -> PortfolioSnapshot | None:
    return (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.is_active == True,  # noqa: E712
        )
        .order_by(PortfolioSnapshot.period_end_date.desc())
        .first()
    )


def income_by_asset_12m(
    db: Session, workspace_id: str, as_of: date
) -> dict[str, Decimal]:
    """Σ distribution.net_amount em BRL por ativo na janela (as_of−12m, as_of].
    Shared helper — a spec 75 deve consumir este mesmo cálculo."""
    try:
        start = as_of.replace(year=as_of.year - 1)
    except ValueError:  # 29/fev
        start = as_of.replace(year=as_of.year - 1, day=28)
    rows = (
        db.query(Distribution.asset_id, func.sum(_net_amount_brl_expr()))
        .filter(
            Distribution.workspace_id == workspace_id,
            Distribution.is_active == True,  # noqa: E712
            Distribution.asset_id.isnot(None),
            Distribution.event_date > start,
            Distribution.event_date <= as_of,
        )
        .group_by(Distribution.asset_id)
        .all()
    )
    return {aid: Decimal(str(v)) for aid, v in rows if v is not None}


def _latest_sector_hints(db: Session, workspace_id: str) -> dict[str, str]:
    """asset_id → 'setor | indústria' do último snapshot de fundamentos."""
    sub = (
        db.query(
            AssetFundamentals.asset_id,
            func.max(AssetFundamentals.snapshot_date).label("d"),
        )
        .filter(AssetFundamentals.workspace_id == workspace_id)
        .group_by(AssetFundamentals.asset_id)
        .subquery()
    )
    rows = (
        db.query(AssetFundamentals.asset_id, AssetFundamentals.raw_payload)
        .join(
            sub,
            (AssetFundamentals.asset_id == sub.c.asset_id)
            & (AssetFundamentals.snapshot_date == sub.c.d),
        )
        .all()
    )
    out: dict[str, str] = {}
    for aid, raw in rows:
        h = sector_hint_from_payload(raw)
        if h:
            out[aid] = h
    return out


def _latest_dividend_yield(db: Session, workspace_id: str) -> dict[str, Decimal]:
    sub = (
        db.query(
            AssetFundamentals.asset_id,
            func.max(AssetFundamentals.snapshot_date).label("d"),
        )
        .filter(AssetFundamentals.workspace_id == workspace_id)
        .group_by(AssetFundamentals.asset_id)
        .subquery()
    )
    rows = (
        db.query(AssetFundamentals.asset_id, AssetFundamentals.dividend_yield_12m)
        .join(
            sub,
            (AssetFundamentals.asset_id == sub.c.asset_id)
            & (AssetFundamentals.snapshot_date == sub.c.d),
        )
        .all()
    )
    return {aid: Decimal(str(dy)) for aid, dy in rows if dy is not None}


@dataclass
class _Targets:
    letters: dict[str, tuple[Decimal, Decimal, Decimal]]  # key → (target, min, max)
    subs: dict[str, Decimal]  # sub key → fração dentro da letra


def _load_targets(db: Session, workspace_id: str) -> _Targets:
    rows = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.workspace_id == workspace_id,
            TargetAllocation.dimension.in_(
                [TargetAllocationDimension.ARCA, TargetAllocationDimension.ARCA_SUB]
            ),
        )
        .all()
    )
    letters: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
    subs: dict[str, Decimal] = {}
    for r in rows:
        if r.dimension == TargetAllocationDimension.ARCA:
            letters[r.key] = (
                Decimal(r.target_pct),
                Decimal(r.min_pct) if r.min_pct is not None else DEFAULT_ARCA_MIN,
                Decimal(r.max_pct) if r.max_pct is not None else DEFAULT_ARCA_MAX,
            )
        else:
            subs[r.key] = Decimal(r.target_pct)
    return _Targets(letters, subs)


# ── Resumo ───────────────────────────────────────────────────────────────


@dataclass
class ArcaAssetRow:
    asset_id: str
    ticker: str | None
    name: str
    asset_class: str
    country: str
    category: str | None
    subcategory: str | None
    derived_category: str | None
    derived_subcategory: str | None
    source: str
    value_brl: Decimal
    income_12m_brl: Decimal
    derived_note: str = ""


@dataclass
class ArcaSubRow:
    key: str
    role: str
    value_brl: Decimal
    pct_of_letter: float
    pct_of_total: float
    target_pct_of_letter: Decimal | None
    target_pct_of_total: Decimal | None
    gap_brl: Decimal | None
    income_12m_brl: Decimal
    yield_12m: float | None


@dataclass
class ArcaLetterRow:
    key: str
    value_brl: Decimal
    current_pct: float
    target_pct: Decimal | None
    min_pct: Decimal
    max_pct: Decimal
    gap_brl: Decimal | None
    status: str  # IN_BAND | BELOW_BAND | ABOVE_BAND | NO_TARGET
    income_12m_brl: Decimal
    yield_12m: float | None
    income_share: float
    income_forward_brl: Decimal
    unclassified_sub_value_brl: Decimal
    subcategories: list[ArcaSubRow] = field(default_factory=list)


@dataclass
class ArcaSummary:
    as_of: str | None
    total_brl: Decimal  # só as 4 letras
    out_of_scope_brl: Decimal
    unmapped_brl: Decimal
    unmapped_count: int
    income_12m_total_brl: Decimal
    attack_pct: float
    defense_pct: float
    unknown_role_pct: float
    targets_configured: bool
    letters: list[ArcaLetterRow]
    assets: list[ArcaAssetRow]


def _ratio(a: Decimal, b: Decimal) -> float:
    return float(a / b) if b > 0 else 0.0


def _status(cur: float, target: Decimal | None, lo: Decimal, hi: Decimal) -> str:
    if target is None:
        return "NO_TARGET"
    if cur < float(lo):
        return "BELOW_BAND"
    if cur > float(hi):
        return "ABOVE_BAND"
    return "IN_BAND"


def arca_summary(db: Session, workspace_id: str) -> ArcaSummary:
    snap = _latest_snapshot(db, workspace_id)
    values: dict[str, Decimal] = {}
    if snap:
        for asset_id, v in (
            db.query(PortfolioSnapshotItem.asset_id, PortfolioSnapshotItem.market_value_brl)
            .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
            .all()
        ):
            values[asset_id] = values.get(asset_id, ZERO) + Decimal(v or 0)
    as_of = snap.period_end_date if snap else date.today()
    income = income_by_asset_12m(db, workspace_id, as_of)
    dy = _latest_dividend_yield(db, workspace_id)
    targets = _load_targets(db, workspace_id)
    hints = _latest_sector_hints(db, workspace_id)

    assets = (
        db.query(Asset)
        .filter(Asset.workspace_id == workspace_id)
        .all()
    )
    rows: list[ArcaAssetRow] = []
    for a in assets:
        v = values.get(a.id, ZERO)
        if not a.is_active and v == 0:
            continue
        hint = hints.get(a.id)
        r = resolve_arca(a, hint)
        d_cat, d_sub, d_note = derive_arca_detail(a, hint)
        rows.append(ArcaAssetRow(
            asset_id=a.id,
            ticker=a.ticker,
            name=a.name,
            asset_class=a.asset_class.value,
            country=a.country,
            category=r.category.value if r.category else None,
            subcategory=r.subcategory.value if r.subcategory else None,
            derived_category=d_cat.value if d_cat else None,
            derived_subcategory=d_sub.value if d_sub else None,
            source=r.source,
            value_brl=v,
            income_12m_brl=income.get(a.id, ZERO),
            derived_note=d_note,
        ))
    rows.sort(key=lambda r: (-r.value_brl, r.name))

    letter_keys = [c.value for c in ARCA_LETTERS]
    in_arca = [r for r in rows if r.category in letter_keys]
    total = sum((r.value_brl for r in in_arca), ZERO)
    income_total = sum((r.income_12m_brl for r in in_arca), ZERO)

    letters: list[ArcaLetterRow] = []
    for lk in letter_keys:
        lrows = [r for r in in_arca if r.category == lk]
        lv = sum((r.value_brl for r in lrows), ZERO)
        linc = sum((r.income_12m_brl for r in lrows), ZERO)
        lfwd = sum(
            ((r.value_brl * dy[r.asset_id]) for r in lrows if r.asset_id in dy), ZERO
        ).quantize(CENT)
        t = targets.letters.get(lk)
        target, lo, hi = (t if t else (None, DEFAULT_ARCA_MIN, DEFAULT_ARCA_MAX))
        cur = _ratio(lv, total)
        subs: list[ArcaSubRow] = []
        for sub in ArcaSubcategory:
            if ARCA_PARENT[sub].value != lk:
                continue
            srows = [r for r in lrows if r.subcategory == sub.value]
            sv = sum((r.value_brl for r in srows), ZERO)
            sinc = sum((r.income_12m_brl for r in srows), ZERO)
            st = targets.subs.get(sub.value)
            if not srows and st is None:
                continue
            st_total = (st * target) if (st is not None and target is not None) else None
            subs.append(ArcaSubRow(
                key=sub.value,
                role=ARCA_ROLE[sub].value,
                value_brl=sv,
                pct_of_letter=_ratio(sv, lv),
                pct_of_total=_ratio(sv, total),
                target_pct_of_letter=st,
                target_pct_of_total=st_total.quantize(Decimal("0.0001")) if st_total is not None else None,
                gap_brl=((st_total * total) - sv).quantize(CENT) if st_total is not None else None,
                income_12m_brl=sinc,
                yield_12m=_ratio(sinc, sv) if sv > 0 else None,
            ))
        letters.append(ArcaLetterRow(
            key=lk,
            value_brl=lv,
            current_pct=cur,
            target_pct=target,
            min_pct=lo,
            max_pct=hi,
            gap_brl=((target * total) - lv).quantize(CENT) if target is not None else None,
            status=_status(cur, target, lo, hi),
            income_12m_brl=linc,
            yield_12m=_ratio(linc, lv) if lv > 0 else None,
            income_share=_ratio(linc, income_total),
            income_forward_brl=lfwd,
            unclassified_sub_value_brl=sum(
                (r.value_brl for r in lrows if r.subcategory is None), ZERO
            ),
            subcategories=subs,
        ))

    attack = sum(
        (r.value_brl for r in in_arca
         if r.subcategory and ARCA_ROLE[ArcaSubcategory(r.subcategory)].value == "ATTACK"),
        ZERO,
    )
    defense = sum(
        (r.value_brl for r in in_arca
         if r.subcategory and ARCA_ROLE[ArcaSubcategory(r.subcategory)].value == "DEFENSE"),
        ZERO,
    )
    unmapped = [r for r in rows if r.category is None]
    return ArcaSummary(
        as_of=snap.period_end_date.isoformat() if snap else None,
        total_brl=total,
        out_of_scope_brl=sum(
            (r.value_brl for r in rows if r.category == ArcaCategory.OUT_OF_SCOPE.value), ZERO
        ),
        unmapped_brl=sum((r.value_brl for r in unmapped), ZERO),
        unmapped_count=len(unmapped),
        income_12m_total_brl=income_total,
        attack_pct=_ratio(attack, total),
        defense_pct=_ratio(defense, total),
        unknown_role_pct=_ratio(total - attack - defense, total),
        targets_configured=bool(targets.letters),
        letters=letters,
        assets=rows,
    )


# ── Simulador de aporte ──────────────────────────────────────────────────


class ArcaPlanError(ValueError):
    pass


def _water_fill(deficits: dict[str, Decimal], amount: Decimal) -> dict[str, Decimal]:
    """Distribui `amount` entre as chaves com déficit positivo, fechando
    primeiro o maior déficit (nivela os déficits restantes por cima).
    Se o dinheiro cobre todos os déficits, devolve exatamente os déficits."""
    pos = {k: d for k, d in deficits.items() if d > 0}
    out = {k: ZERO for k in deficits}
    if amount <= 0 or not pos:
        return out
    need = sum(pos.values(), ZERO)
    if need <= amount:
        out.update(pos)
        return out
    # Achar nível L tal que Σ max(0, d − L) = amount.
    ds = sorted(pos.values(), reverse=True)
    level = ZERO
    for i in range(len(ds)):
        top = ds[: i + 1]
        cand = (sum(top, ZERO) - amount) / (i + 1)
        nxt = ds[i + 1] if i + 1 < len(ds) else ZERO
        if cand >= nxt:
            level = cand
            break
    for k, d in pos.items():
        out[k] = max(ZERO, d - level)
    return out


def _round_preserving(alloc: dict[str, Decimal], total: Decimal) -> dict[str, Decimal]:
    """Arredonda para centavos e joga o resíduo na maior parcela, para a
    soma bater exatamente com o aporte."""
    out = {k: v.quantize(CENT) for k, v in alloc.items()}
    diff = total.quantize(CENT) - sum(out.values(), ZERO)
    if diff and out:
        k = max(out, key=lambda x: out[x])
        out[k] += diff
    return out


def _split_rest(
    weights: dict[str, Decimal], amount: Decimal
) -> dict[str, Decimal]:
    total_w = sum(weights.values(), ZERO)
    if amount <= 0 or total_w <= 0:
        return {k: ZERO for k in weights}
    return {k: amount * w / total_w for k, w in weights.items()}


@dataclass
class PlanSubRow:
    key: str
    amount_brl: Decimal


@dataclass
class PlanLetterRow:
    key: str
    current_brl: Decimal
    amount_brl: Decimal
    after_brl: Decimal
    after_pct: float
    target_pct: Decimal
    sell_suggestion_brl: Decimal
    subcategories: list[PlanSubRow]


@dataclass
class ContributionPlan:
    amount_brl: Decimal
    total_after_brl: Decimal
    letters: list[PlanLetterRow]


def contribution_plan(
    db: Session, workspace_id: str, amount: Decimal
) -> ContributionPlan:
    if amount <= 0:
        raise ArcaPlanError("O aporte precisa ser maior que zero.")
    summary = arca_summary(db, workspace_id)
    targets = _load_targets(db, workspace_id)
    if not targets.letters:
        raise ArcaPlanError("Configure as metas ARCA antes de simular.")

    cur = {lr.key: lr.value_brl for lr in summary.letters}
    total_after = summary.total_brl + amount
    tgt = {k: t[0] for k, t in targets.letters.items()}
    deficits = {k: tgt.get(k, ZERO) * total_after - cur.get(k, ZERO) for k in cur}
    alloc = _water_fill(deficits, amount)
    leftover = amount - sum(alloc.values(), ZERO)
    if leftover > 0:
        extra = _split_rest(tgt, leftover)
        for k, v in extra.items():
            alloc[k] = alloc.get(k, ZERO) + v
    alloc = _round_preserving({k: v for k, v in alloc.items() if k in tgt}, amount)

    letters: list[PlanLetterRow] = []
    for lr in summary.letters:
        k = lr.key
        if k not in tgt:
            continue
        a = alloc.get(k, ZERO)
        after = cur[k] + a
        _, _, hi = targets.letters[k]
        sell = max(ZERO, after - hi * total_after)

        # Dentro da letra: mesma lógica nas subcategorias com meta.
        sub_t = {
            s: f for s, f in targets.subs.items() if ARCA_PARENT[ArcaSubcategory(s)].value == k
        }
        sub_rows: list[PlanSubRow] = []
        if sub_t and a > 0:
            sub_cur = {s.key: s.value_brl for s in lr.subcategories}
            sub_def = {s: f * after - sub_cur.get(s, ZERO) for s, f in sub_t.items()}
            sub_alloc = _water_fill(sub_def, a)
            rest = a - sum(sub_alloc.values(), ZERO)
            if rest > 0:
                for s, v in _split_rest(sub_t, rest).items():
                    sub_alloc[s] = sub_alloc.get(s, ZERO) + v
            sub_alloc = _round_preserving(sub_alloc, a)
            sub_rows = [
                PlanSubRow(key=s, amount_brl=v)
                for s, v in sorted(sub_alloc.items(), key=lambda kv: -kv[1])
                if v > 0
            ]
        letters.append(PlanLetterRow(
            key=k,
            current_brl=cur[k],
            amount_brl=a,
            after_brl=after.quantize(CENT),
            after_pct=_ratio(after, total_after),
            target_pct=tgt[k],
            sell_suggestion_brl=sell.quantize(CENT),
            subcategories=sub_rows,
        ))
    return ContributionPlan(amount_brl=amount, total_after_brl=total_after, letters=letters)
