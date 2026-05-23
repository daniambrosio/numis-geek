"""Seed the two real options from docs/options-rationale.md §13.

ITUBR364 — PUT ITUB4 strike R$ 36,40 vence 19/06/2026
  SELL_OPEN 1.000 @ R$ 0,09 em 02/05/2026 (R$ 90 received)
ITUBF475 — CALL ITUB4 strike R$ 47,50 vence 19/06/2026
  SELL_OPEN 1.000 @ R$ 0,34 em 05/05/2026 (R$ 340 received)
"""
from __future__ import annotations

import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.models.asset import Asset, AssetClass, OptionType
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.account import Currency


ITUB4_TICKER = "ITUB4"


def seed(db: Session):
    itub4 = db.query(Asset).filter(Asset.ticker == ITUB4_TICKER).first()
    if not itub4:
        raise RuntimeError("ITUB4 asset not found.")

    options_spec = [
        {
            "ticker": "ITUBR364",
            "name": "PUT ITUB4 · strike R$ 36,40 · vence 19/06/2026",
            "option_type": OptionType.PUT,
            "strike": Decimal("36.40"),
            "movement_date": date(2026, 5, 2),
            "quantity": Decimal("1000"),
            "price_per_share": Decimal("0.09"),
        },
        {
            "ticker": "ITUBF475",
            "name": "CALL ITUB4 · strike R$ 47,50 · vence 19/06/2026",
            "option_type": OptionType.CALL,
            "strike": Decimal("47.50"),
            "movement_date": date(2026, 5, 5),
            "quantity": Decimal("1000"),
            "price_per_share": Decimal("0.34"),
        },
    ]
    now = datetime.now(timezone.utc)
    for spec in options_spec:
        existing = db.query(Asset).filter(Asset.ticker == spec["ticker"]).first()
        if existing:
            print(f"skip {spec['ticker']!r}: already exists ({existing.id})")
            continue
        opt = Asset(
            id=str(uuid.uuid4()),
            workspace_id=itub4.workspace_id,
            account_id=itub4.account_id,
            asset_class=AssetClass.OPTION,
            country="BR",
            name=spec["name"],
            ticker=spec["ticker"],
            currency=Currency.BRL,
            is_active=True,
            underlying_id=itub4.id,
            option_type=spec["option_type"],
            strike_price=spec["strike"],
            expiration_date=date(2026, 6, 19),
            contract_size=100,
            created_at=now,
            updated_at=now,
        )
        db.add(opt)
        db.flush()
        gross = spec["quantity"] * spec["price_per_share"]
        db.add(AssetMovement(
            id=str(uuid.uuid4()),
            workspace_id=itub4.workspace_id,
            asset_id=opt.id,
            type=AssetMovementType.SELL_OPEN,
            event_date=spec["movement_date"],
            quantity=spec["quantity"],
            unit_price=spec["price_per_share"],
            gross_amount=gross,
            fee=Decimal("0"),
            tax=Decimal("0"),
            net_amount=gross,
            currency=Currency.BRL,
            fx_rate=Decimal("1"),
            notes=f"SELL_OPEN seeded por scripts/seed_options.py",
            is_active=True,
            created_at=now,
            updated_at=now,
        ))
        db.flush()
        print(f"created {spec['ticker']!r}: option id={opt.id}, SELL_OPEN gross={gross}")
    db.commit()


def main():
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
