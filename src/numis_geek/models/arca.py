"""Spec 85 — ARCA (Ações · Real Estate · Caixa · Ativos internacionais).

Enums only; the classification lives as nullable overrides on `asset`
(`arca_category`, `arca_subcategory`, stored as strings) and the derived
default comes from `services/arca.py::derive_arca`.
"""
import enum


class ArcaCategory(str, enum.Enum):
    EQUITY_BR = "EQUITY_BR"        # A — Ações brasileiras
    REAL_ESTATE = "REAL_ESTATE"    # R — Real Estate
    CASH = "CASH"                  # C — Caixa (renda fixa)
    GLOBAL = "GLOBAL"              # A — Ativos internacionais / alternativos
    OUT_OF_SCOPE = "OUT_OF_SCOPE"  # fora da ARCA (veículo, FGTS, imóvel de uso…)


ARCA_LETTERS: tuple[ArcaCategory, ...] = (
    ArcaCategory.EQUITY_BR,
    ArcaCategory.REAL_ESTATE,
    ArcaCategory.CASH,
    ArcaCategory.GLOBAL,
)


class ArcaSubcategory(str, enum.Enum):
    # CASH
    CASH_POST_FIXED = "CASH_POST_FIXED"
    CASH_PRE_FIXED = "CASH_PRE_FIXED"
    CASH_INFLATION = "CASH_INFLATION"
    # REAL_ESTATE
    RE_BRICK = "RE_BRICK"
    RE_FOF = "RE_FOF"
    RE_PAPER_CDI = "RE_PAPER_CDI"
    RE_PAPER_IPCA = "RE_PAPER_IPCA"
    RE_DIRECT = "RE_DIRECT"
    # EQUITY_BR
    EQ_DEFENSIVE = "EQ_DEFENSIVE"
    EQ_DOLLAR = "EQ_DOLLAR"
    EQ_ACCELERATOR = "EQ_ACCELERATOR"
    # GLOBAL
    GL_FIXED_INCOME = "GL_FIXED_INCOME"
    GL_GOLD = "GL_GOLD"
    GL_CRYPTO = "GL_CRYPTO"
    GL_EQUITY = "GL_EQUITY"
    GL_REIT = "GL_REIT"


_PREFIX_TO_PARENT = {
    "CASH_": ArcaCategory.CASH,
    "RE_": ArcaCategory.REAL_ESTATE,
    "EQ_": ArcaCategory.EQUITY_BR,
    "GL_": ArcaCategory.GLOBAL,
}

ARCA_PARENT: dict[ArcaSubcategory, ArcaCategory] = {
    sub: next(p for pre, p in _PREFIX_TO_PARENT.items() if sub.value.startswith(pre))
    for sub in ArcaSubcategory
}


class ArcaRole(str, enum.Enum):
    """Papel no vídeo de referência: 'ataque' ganha no cenário bom,
    'defesa' segura no ruim. Usado só para exibir % ataque × defesa."""
    ATTACK = "ATTACK"
    DEFENSE = "DEFENSE"


ARCA_ROLE: dict[ArcaSubcategory, ArcaRole] = {
    ArcaSubcategory.CASH_POST_FIXED: ArcaRole.DEFENSE,
    ArcaSubcategory.CASH_PRE_FIXED: ArcaRole.DEFENSE,
    ArcaSubcategory.CASH_INFLATION: ArcaRole.DEFENSE,
    ArcaSubcategory.RE_BRICK: ArcaRole.ATTACK,
    ArcaSubcategory.RE_FOF: ArcaRole.ATTACK,
    ArcaSubcategory.RE_PAPER_CDI: ArcaRole.DEFENSE,
    ArcaSubcategory.RE_PAPER_IPCA: ArcaRole.DEFENSE,
    ArcaSubcategory.RE_DIRECT: ArcaRole.DEFENSE,
    ArcaSubcategory.EQ_DEFENSIVE: ArcaRole.DEFENSE,
    ArcaSubcategory.EQ_DOLLAR: ArcaRole.DEFENSE,
    ArcaSubcategory.EQ_ACCELERATOR: ArcaRole.ATTACK,
    ArcaSubcategory.GL_FIXED_INCOME: ArcaRole.DEFENSE,
    ArcaSubcategory.GL_GOLD: ArcaRole.DEFENSE,
    ArcaSubcategory.GL_CRYPTO: ArcaRole.ATTACK,
    ArcaSubcategory.GL_EQUITY: ArcaRole.ATTACK,
    ArcaSubcategory.GL_REIT: ArcaRole.ATTACK,
}
