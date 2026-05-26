"""Spec follow-up — tests for services/fx.resolve_fx_rate.

Honors client-provided values, auto-fills from PTAX when None, falls
back to 1.0 when PTAX table has no rate within walkback.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.services.fx import resolve_fx_rate


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
def session():
    s = TestSession()
    try:
        yield s
    finally:
        s.rollback()
        # PTAXRate seeded in tests commits, so explicit cleanup is needed
        # between tests (TestSession shares the in-memory engine module-wide).
        s.query(PTAXRate).delete()
        s.commit()
        s.close()


def _seed_ptax(db, when: date, rate: str) -> None:
    db.add(PTAXRate(
        id=str(uuid.uuid4()),
        date=when, rate=Decimal(rate),
        source="BCB_SGS",
        fetched_at=datetime.now(timezone.utc),
    ))
    db.commit()


def test_resolve_honors_client_value_when_provided(session):
    _seed_ptax(session, date(2026, 5, 22), "5.0134")

    # Client passed 4.9999 — that must win (manual override).
    result = resolve_fx_rate(
        session, date(2026, 5, 22), client_value=Decimal("4.9999"),
    )
    assert result == Decimal("4.9999")


def test_resolve_autofills_from_ptax_when_none(session):
    _seed_ptax(session, date(2026, 5, 22), "5.0134")

    result = resolve_fx_rate(session, date(2026, 5, 22), client_value=None)
    assert result == Decimal("5.0134")


def test_resolve_walks_back_on_weekend(session):
    """Sat/Sun resolves to Friday's PTAX (services/fx already handles)."""
    _seed_ptax(session, date(2026, 5, 22), "5.0134")  # Friday

    # Sunday → walks back to Friday
    result = resolve_fx_rate(session, date(2026, 5, 24), client_value=None)
    assert result == Decimal("5.0134")


def test_resolve_falls_back_to_1_when_no_ptax(session):
    """Outside walkback window → fallback 1.0 (degraded but never crashes)."""
    # Empty PTAX table — no row within walkback window.
    result = resolve_fx_rate(session, date(2020, 1, 1), client_value=None)
    assert result == Decimal("1.0")


def test_resolve_falls_back_to_custom_value(session):
    result = resolve_fx_rate(
        session, date(2020, 1, 1),
        client_value=None,
        fallback=Decimal("0.99"),
    )
    assert result == Decimal("0.99")
