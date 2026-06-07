"""Spec 58 Stage 4 — unit tests for the Avenue proventos CSV parser.

Pure unit tests: no DB, no LLM. The parser takes raw CSV bytes and
emits a payload dict whose shape mirrors what an LLM would emit for a
BROKER_INCOME job — so the apply layer is source-agnostic.
"""
from __future__ import annotations

import pytest

from numis_geek.services.extraction_parsers.avenue_proventos import (
    parse_avenue_proventos_csv,
)


HEADER = "Data transação,Data liquidação,Descrição,Valor,Saldo\n"


def _parse(rows: list[str]) -> dict:
    return parse_avenue_proventos_csv((HEADER + "\n".join(rows) + "\n").encode("utf-8"))


# ── basic per-pattern coverage ──────────────────────────────────────────────


def test_dividend_paired_with_tax():
    p = _parse([
        "27/05/2026,27/05/2026,Dividendos de WMT,12.32,727.33",
        "27/05/2026,27/05/2026,Imposto sobre dividendo de WMT,-3.70,723.63",
    ])
    assert len(p["events"]) == 1
    e = p["events"][0]
    assert e["event_date"] == "2026-05-27"
    assert e["ticker_raw"] == "WMT"
    assert e["type"] == "DIVIDEND"
    assert e["gross_amount"] == 12.32
    assert e["tax_amount"] == 3.70
    assert e["net_amount"] == pytest.approx(8.62)
    assert e["currency"] == "USD"


def test_dividend_with_adr_fee_combines_into_tax():
    p = _parse([
        "13/05/2026,13/05/2026,Dividendos de BTI,27.00,322.71",
        "13/05/2026,13/05/2026,Taxa sobre ADR de BTI,-0.32,295.71",
    ])
    assert len(p["events"]) == 1
    e = p["events"][0]
    assert e["ticker_raw"] == "BTI"
    assert e["gross_amount"] == 27.00
    assert e["tax_amount"] == 0.32
    assert e["net_amount"] == pytest.approx(26.68)


def test_dividend_with_tax_and_adr_fee_sums_both_into_tax():
    p = _parse([
        "13/05/2026,13/05/2026,Dividendos de BTI,27.00,322.71",
        "13/05/2026,13/05/2026,Imposto sobre dividendo de BTI,-8.10,314.61",
        "13/05/2026,13/05/2026,Taxa sobre ADR de BTI,-0.32,314.29",
    ])
    e = p["events"][0]
    assert e["tax_amount"] == pytest.approx(8.42)
    assert e["net_amount"] == pytest.approx(18.58)


def test_coupon_alone_is_interest_with_no_tax():
    """Treasury coupons come without a paired tax row in Avenue's CSV."""
    p = _parse([
        "16/05/2026,18/05/2026,Cupom de T 4.25 15/11/34,212.50,718.71",
    ])
    e = p["events"][0]
    assert e["type"] == "INTEREST"
    assert e["ticker_raw"] == "T 4.25 15/11/34"
    assert e["event_date"] == "2026-05-18"  # uses Data liquidação
    assert e["gross_amount"] == 212.50
    assert e["tax_amount"] is None
    assert e["net_amount"] == 212.50


def test_securities_lending_paired():
    p = _parse([
        "13/05/2026,13/05/2026,Rentabilidade de aluguel de ativo,0.64,323.35",
        "13/05/2026,13/05/2026,Imposto de aluguel de ativo,-0.19,323.16",
    ])
    e = p["events"][0]
    assert e["type"] == "SECURITIES_LENDING"
    assert e["ticker_raw"] is None
    assert e["gross_amount"] == 0.64
    assert e["tax_amount"] == 0.19
    assert e["net_amount"] == pytest.approx(0.45)


# ── pairing edge cases ─────────────────────────────────────────────────────


def test_tax_appearing_before_gross_still_pairs():
    """CSV row order shouldn't affect pairing — group by (date, ticker, family)."""
    p = _parse([
        "27/05/2026,27/05/2026,Imposto sobre dividendo de WMT,-3.70,723.63",
        "27/05/2026,27/05/2026,Dividendos de WMT,12.32,727.33",
    ])
    assert len(p["events"]) == 1
    e = p["events"][0]
    assert e["gross_amount"] == 12.32
    assert e["tax_amount"] == 3.70


def test_same_ticker_different_dates_are_separate_events():
    """Two VCLT dividends with different settlement dates → 2 events."""
    p = _parse([
        "06/05/2026,06/05/2026,Dividendos de VCLT,0.15,276.37",
        "06/05/2026,06/05/2026,Imposto sobre dividendo de VCLT,-0.05,276.32",
        "06/05/2026,07/05/2026,Dividendos de VCLT,32.41,285.94",
        "06/05/2026,07/05/2026,Imposto sobre dividendo de VCLT,-9.72,276.22",
    ])
    assert len(p["events"]) == 2
    dates = sorted(e["event_date"] for e in p["events"])
    assert dates == ["2026-05-06", "2026-05-07"]


def test_orphan_tax_row_without_gross_is_skipped():
    """Tax row without a matching gross row → no event emitted."""
    p = _parse([
        "27/05/2026,27/05/2026,Imposto sobre dividendo de XYZ,-3.70,723.63",
    ])
    assert p["events"] == []


def test_unknown_description_recorded_in_diagnostics():
    p = _parse([
        "27/05/2026,27/05/2026,Algo completamente novo,5.00,100.00",
    ])
    assert p["events"] == []
    assert "Algo completamente novo" in p["_unparsed_descriptions"]


def test_uses_liquidacao_date_not_transacao():
    """When the two dates differ, event_date follows Data liquidação (cash arrives)."""
    p = _parse([
        "01/05/2026,04/05/2026,Dividendos de XYZ,10.00,100.00",
    ])
    assert p["events"][0]["event_date"] == "2026-05-04"


def test_falls_back_to_transacao_when_liquidacao_missing():
    p = _parse([
        "01/05/2026,,Dividendos de XYZ,10.00,100.00",
    ])
    assert p["events"][0]["event_date"] == "2026-05-01"


# ── real CSV regression ────────────────────────────────────────────────────


def test_real_avenue_csv_smoke():
    """Run the parser on the real fixture file and assert a sane shape."""
    import pathlib
    p = pathlib.Path("/Users/dambrosio/Downloads/avenue-report-statement (4).csv")
    if not p.exists():
        pytest.skip("real Avenue fixture not present on this machine")
    payload = parse_avenue_proventos_csv(p.read_bytes())
    assert payload["broker_name"] == "Avenue"
    assert payload["as_of_date"] == "2026-05-27"
    assert len(payload["events"]) == 20
    assert payload["_unparsed_descriptions"] == []
    # Spot-check a few well-known rows.
    by_key = {(e["event_date"], e["ticker_raw"]): e for e in payload["events"]}
    assert by_key[("2026-05-27", "WMT")]["net_amount"] == pytest.approx(8.62)
    assert by_key[("2026-05-13", "BTI")]["tax_amount"] == pytest.approx(0.32)
    assert by_key[("2026-05-18", "T 4.25 15/11/34")]["type"] == "INTEREST"
    assert by_key[("2026-05-13", None)]["type"] == "SECURITIES_LENDING"


# ── helpers / output shape ─────────────────────────────────────────────────


def test_empty_csv_returns_empty_events():
    p = parse_avenue_proventos_csv(HEADER.encode("utf-8"))
    assert p["events"] == []
    assert p["as_of_date"] is None
    assert p["broker_name"] == "Avenue"


def test_payload_shape_mirrors_llm_broker_income():
    """Same top-level keys as the LLM BROKER_INCOME schema."""
    p = _parse([
        "27/05/2026,27/05/2026,Dividendos de WMT,12.32,727.33",
    ])
    # Top-level
    assert set(p.keys()) >= {"as_of_date", "broker_name", "events"}
    # Per-event
    e = p["events"][0]
    assert set(e.keys()) >= {
        "event_date", "ticker_raw", "type",
        "gross_amount", "tax_amount", "net_amount",
        "currency", "notes", "confidence",
    }


# ── parser_for registry ─────────────────────────────────────────────────────


def test_parser_for_routes_avenue_income_csv():
    from numis_geek.services.extraction_parsers import parser_for
    from numis_geek.models.extraction_job import ExtractionSourceHint

    fn = parser_for(
        institution_short_name="Avenue",
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        mime_type="text/csv",
    )
    assert fn is parse_avenue_proventos_csv


def test_parser_for_returns_none_for_unknown_combo():
    from numis_geek.services.extraction_parsers import parser_for
    from numis_geek.models.extraction_job import ExtractionSourceHint

    # Unknown FI
    assert parser_for(
        institution_short_name="XP", source_hint=ExtractionSourceHint.BROKER_INCOME,
        mime_type="text/csv",
    ) is None
    # Avenue but positions, not income
    assert parser_for(
        institution_short_name="Avenue",
        source_hint=ExtractionSourceHint.BROKER_POSITION,
        mime_type="text/csv",
    ) is None
    # Avenue income but PDF instead of CSV
    assert parser_for(
        institution_short_name="Avenue",
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        mime_type="application/pdf",
    ) is None
    # Missing FI
    assert parser_for(
        institution_short_name=None,
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        mime_type="text/csv",
    ) is None


def test_parser_for_case_insensitive_fi_name():
    from numis_geek.services.extraction_parsers import parser_for
    from numis_geek.models.extraction_job import ExtractionSourceHint

    for variant in ("avenue", "AVENUE", " Avenue "):
        fn = parser_for(
            institution_short_name=variant,
            source_hint=ExtractionSourceHint.BROKER_INCOME,
            mime_type="text/csv",
        )
        assert fn is parse_avenue_proventos_csv


# ── End-to-end: parser → run_extraction → confirm → Distribution rows ──────


def test_e2e_avenue_proventos_creates_distributions(tmp_path, monkeypatch):
    """Stages A+B+C wired together. Upload Avenue CSV → deterministic
    parser runs (no LLM) → confirm creates Distribution rows.
    Re-running with same content is idempotent (duplicate bucket)."""
    import uuid as _uuid
    from datetime import date as _date, datetime, timezone
    from decimal import Decimal as _D
    import bcrypt
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from numis_geek.db.base import Base
    import numis_geek.models  # noqa: F401
    from numis_geek.models.account import Account, AccountType, Currency
    from numis_geek.models.asset import Asset, AssetClass, PriceSource
    from numis_geek.models.attachment import (
        Attachment, AttachmentKind, AttachmentSourceType,
    )
    from numis_geek.models.distribution import Distribution
    from numis_geek.models.extraction_job import (
        ExtractionSourceHint, ExtractionStatus,
    )
    from numis_geek.models.financial_institution import FinancialInstitution
    from numis_geek.models.portfolio_snapshot import (
        PortfolioSnapshot, SnapshotSource, SnapshotStatus,
    )
    from numis_geek.models.user import User, UserRole
    from numis_geek.services import attachment_storage
    from numis_geek.services import extraction as extraction_service
    from numis_geek.services.workspace import WorkspaceService

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    s = Session()

    # Storage root → tmp_path for the test.
    monkeypatch.setattr(attachment_storage, "ROOT", tmp_path)

    now = datetime.now(timezone.utc)
    ws = WorkspaceService(s).create("AvenueProventos-WS")
    user = User(
        id=str(_uuid.uuid4()), workspace_id=ws.id,
        email="provs@test.com", name="P",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.admin, is_active=True,
        created_at=now, updated_at=now,
    )
    fi = FinancialInstitution(
        id=str(_uuid.uuid4()), long_name="Avenue", short_name="Avenue",
        country="US", is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(_uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="Avenue Inv", account_type=AccountType.investment,
        currency=Currency.USD, is_active=True, created_at=now, updated_at=now,
    )
    # Asset to match a dividend (WMT). Treasury and lending intentionally
    # left out so we exercise the orphan path too.
    wmt = Asset(
        id=str(_uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="US",
        name="Walmart Inc", ticker="WMT",
        currency=Currency.USD, current_price=_D("80"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    snap = PortfolioSnapshot(
        id=str(_uuid.uuid4()), workspace_id=ws.id,
        period_end_date=_date(2026, 5, 31),
        total_value_brl=_D("0"), total_value_usd=_D("0"),
        total_invested_brl=_D("0"), total_received_brl=_D("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        notion_sync_status="PENDING",
    )
    s.add_all([user, fi, acc, wmt, snap])
    s.flush()

    # Save a minimal Avenue CSV with WMT (matches) + a treasury cupom
    # (orphan: no asset) + lending (no ticker, NOT orphan since asset_id nullable).
    csv_bytes = (
        "Data transação,Data liquidação,Descrição,Valor,Saldo\n"
        "27/05/2026,27/05/2026,Dividendos de WMT,12.32,727.33\n"
        "27/05/2026,27/05/2026,Imposto sobre dividendo de WMT,-3.70,723.63\n"
        "16/05/2026,18/05/2026,Cupom de T 4.25 15/11/34,212.50,718.71\n"
        "13/05/2026,13/05/2026,Rentabilidade de aluguel de ativo,0.64,0.64\n"
        "13/05/2026,13/05/2026,Imposto de aluguel de ativo,-0.19,0.45\n"
    ).encode("utf-8")
    saved = attachment_storage.save_bytes(ws.id, csv_bytes, "text/csv")
    att = Attachment(
        id=str(_uuid.uuid4()), workspace_id=ws.id,
        source_type=AttachmentSourceType.SNAPSHOT, source_id=snap.id,
        kind=AttachmentKind.CSV, filename="proventos.csv", mime_type="text/csv",
        size_bytes=saved.size_bytes, storage_key=saved.storage_key,
        uploaded_at=now, is_active=True,
    )
    s.add(att)
    s.flush()

    # ── Run extraction ──
    job = extraction_service.create_and_run(
        s,
        workspace_id=ws.id,
        attachment_id=att.id,
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        snapshot_id=snap.id,
        institution_id=fi.id,
        user_id=user.id,
        user_email=user.email,
    )
    assert job.status == ExtractionStatus.EXTRACTED, job.error_message
    # Deterministic path → no LLM cost, prompt_version marker.
    assert job.prompt_version == "deterministic:parse_avenue_proventos_csv"
    assert job.cost_usd == _D("0")
    assert job.input_tokens == 0

    # 3 events parsed (WMT dividend, T 4.25 coupon, lending).
    assert len(job.extracted_json["events"]) == 3

    # ── Preview (read-only) ──
    preview = extraction_service.preview_bulk_income(s, job_id=job.id)
    # WMT (matched) + lending (no ticker → allowed) = 2 will apply.
    # T 4.25 coupon → orphan (no asset cadastrado).
    assert preview.applied_count == 2
    assert {o["ticker"] for o in preview.bulk_detail.orphan} == {"T 4.25 15/11/34"}

    # ── Confirm (writes) ──
    result = extraction_service.confirm_extraction(
        s, job_id=job.id, user_id=user.id, user_email=user.email,
    )
    assert result.applied_count == 2
    assert {a["ticker"] for a in result.bulk_detail.applied} == {"WMT", None}
    assert result.bulk_detail.matched_no_pendency == []  # no duplicates yet

    # Distribution rows persisted.
    dists = s.query(Distribution).filter(Distribution.workspace_id == ws.id).all()
    assert len(dists) == 2
    by_type = {d.type.value: d for d in dists}
    wmt_dist = by_type["DIVIDEND"]
    assert wmt_dist.asset_id == wmt.id
    assert wmt_dist.gross_amount == _D("12.32")
    assert wmt_dist.tax == _D("3.70")
    assert wmt_dist.net_amount == _D("8.62")
    assert wmt_dist.event_date == _date(2026, 5, 27)
    lending_dist = by_type["SECURITIES_LENDING"]
    assert lending_dist.asset_id is None
    assert lending_dist.net_amount == _D("0.45")

    # ── Idempotency: re-confirm same job → duplicates, no new Distributions ──
    s.commit()  # commit so the duplicate query in classify sees the rows
    # New job for the SAME csv (simulates re-upload).
    att2 = Attachment(
        id=str(_uuid.uuid4()), workspace_id=ws.id,
        source_type=AttachmentSourceType.SNAPSHOT, source_id=snap.id,
        kind=AttachmentKind.CSV, filename="proventos2.csv", mime_type="text/csv",
        size_bytes=saved.size_bytes, storage_key=saved.storage_key,  # same blob
        uploaded_at=now, is_active=True,
    )
    s.add(att2)
    s.flush()
    job2 = extraction_service.create_and_run(
        s,
        workspace_id=ws.id,
        attachment_id=att2.id,
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        snapshot_id=snap.id,
        institution_id=fi.id,
        user_id=user.id,
        user_email=user.email,
    )
    result2 = extraction_service.confirm_extraction(
        s, job_id=job2.id, user_id=user.id, user_email=user.email,
    )
    # Re-applied = 0; the WMT + lending events flagged as duplicate.
    assert result2.applied_count == 0
    duplicates = {(r["ticker"], r["type"]) for r in result2.bulk_detail.matched_no_pendency}
    assert ("WMT", "DIVIDEND") in duplicates
    assert (None, "SECURITIES_LENDING") in duplicates
    # Still only 2 Distributions in DB.
    s.commit()
    final_count = s.query(Distribution).filter(Distribution.workspace_id == ws.id).count()
    assert final_count == 2
