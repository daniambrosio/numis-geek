"""One-off datafix: backfill fx_rate em Distribution rows USD com fx_rate=1.

Bug: _apply_bulk_income_to_snapshot gravou fx_rate=Decimal('1.0') hardcoded
ao criar Distribution rows do extrato Avenue. Pra eventos USD isso quebrou
todas as conversões BRL na UI (R$ X em vez de R$ X*PTAX, sub-conta ~5x).

Script:
1. SELECT distribution WHERE currency='USD' AND fx_rate=1 AND is_active=1
2. Pra cada row, busca PTAX da event_date via services.fx.fx_rate_on
3. UPDATE em batch, log do antes/depois.

Safety:
- DRY-RUN por default. Passar --apply pra realmente escrever.
- Reporta count + sample antes/depois.
- Não toca em BRL distributions (essas já têm fx=1 correto).

Uso:
    uv run python scripts/backfill_distribution_fx_rate.py            # dry-run
    uv run python scripts/backfill_distribution_fx_rate.py --apply    # commit
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from numis_geek.db.session import SessionLocal
from numis_geek.models.account import Currency
from numis_geek.models.distribution import Distribution
from numis_geek.services.fx import FxRateNotFound, fx_rate_on


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Escreve no DB (default: dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = (
            db.query(Distribution)
            .filter(
                Distribution.currency == Currency.USD,
                Distribution.fx_rate == Decimal("1"),
                Distribution.is_active.is_(True),
            )
            .all()
        )
        print(f"Candidatos: {len(rows)} distribution USD com fx_rate=1")
        if not rows:
            print("Nada pra fazer.")
            return 0

        updated = 0
        no_ptax: list[str] = []
        sample_before: list[str] = []
        sample_after: list[str] = []
        for r in rows:
            try:
                ptax = fx_rate_on(db, r.event_date)
            except FxRateNotFound:
                no_ptax.append(f"  {r.event_date} {r.id}")
                continue
            if len(sample_before) < 5:
                sample_before.append(
                    f"  {r.event_date} net=${r.net_amount} fx={r.fx_rate}"
                    f" → R$ {r.net_amount * r.fx_rate}"
                )
                sample_after.append(
                    f"  {r.event_date} net=${r.net_amount} fx={ptax}"
                    f" → R$ {r.net_amount * ptax}"
                )
            r.fx_rate = ptax
            updated += 1

        print(f"\nUpdates planejados: {updated}")
        if no_ptax:
            print(f"Sem PTAX disponível ({len(no_ptax)}):")
            for line in no_ptax[:5]:
                print(line)
        print("\nAmostra (antes → depois):")
        for b, a in zip(sample_before, sample_after):
            print(f"  ANTES{b}")
            print(f"  DEPOIS{a}")

        if args.apply:
            db.commit()
            print(f"\n✅ COMMIT: {updated} rows atualizadas.")
        else:
            db.rollback()
            print(f"\n[DRY-RUN] rollback. Roda com --apply pra escrever.")

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
