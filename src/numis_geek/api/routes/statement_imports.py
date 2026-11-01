"""Spec 71 — Import de extrato (conta corrente) e fatura (cartão).

Entry point of the import flow on top of the ExtractionJob pipeline:

    POST /accounts/{id}/statement-imports     (multipart file)
    POST /credit-cards/{id}/invoice-imports   (multipart file)
        → dedup layer 1 (content_hash), Attachment anchored on the
          account/card, ExtractionJob (BANK_STATEMENT / CARD_INVOICE) run
          inline (LLM can take 1–3 min — proxy at 600 s).
    GET  same paths → import history (period, status, N transações).

Review/apply reuse `/extractions/{id}/preview|confirm|reject`.
Any workspace user imports (same rule as transactions); sysadmin passes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Account, AccountType
from numis_geek.models.attachment import Attachment, AttachmentSourceType
from numis_geek.models.credit_card import CreditCardAccount
from numis_geek.models.extraction_job import (
    ExtractionJob, ExtractionSourceHint, ExtractionStatus,
)
from numis_geek.models.transaction import Transaction
from numis_geek.models.user import User, UserRole
from numis_geek.services import attachment_storage
from numis_geek.services import extraction as extraction_service
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(tags=["statement-imports"])

_IMPORT_SOURCES = (AttachmentSourceType.ACCOUNT, AttachmentSourceType.CREDIT_CARD_ACCOUNT)

# Browsers send "" / octet-stream for .ofx (and sometimes for the rest).
_EXT_MIME = {
    "ofx": "application/x-ofx",
    "qfx": "application/x-ofx",
    "pdf": "application/pdf",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


class StatementImportOut(BaseModel):
    id: str
    status: str
    source_hint: str
    attachment_id: str
    filename: str | None
    checking_account_id: str | None
    credit_card_account_id: str | None
    statement_period_start: str | None
    statement_period_end: str | None
    line_count: int
    transaction_count: int
    error_message: str | None
    cost_usd: str | None
    created_at: str
    confirmed_at: str | None
    # True quando o upload devolveu um job já extraído do mesmo arquivo
    # (review interrompido) em vez de chamar o LLM de novo.
    resumed: bool = False


def _out(db: Session, j: ExtractionJob, *, resumed: bool = False) -> StatementImportOut:
    att = db.get(Attachment, j.attachment_id)
    n_tx = db.query(func.count(Transaction.id)).filter(Transaction.extraction_job_id == j.id).scalar() or 0
    return StatementImportOut(
        id=j.id,
        status=j.status.value,
        source_hint=j.source_hint.value,
        attachment_id=j.attachment_id,
        filename=att.filename if att else None,
        checking_account_id=j.checking_account_id,
        credit_card_account_id=j.credit_card_account_id,
        statement_period_start=j.statement_period_start.isoformat() if j.statement_period_start else None,
        statement_period_end=j.statement_period_end.isoformat() if j.statement_period_end else None,
        line_count=len((j.extracted_json or {}).get("transactions") or []),
        transaction_count=n_tx,
        error_message=j.error_message,
        cost_usd=str(j.cost_usd) if j.cost_usd is not None else None,
        created_at=j.created_at.isoformat() if j.created_at else "",
        confirmed_at=j.confirmed_at.isoformat() if j.confirmed_at else None,
        resumed=resumed,
    )


def _scoped(row, current_user: UserContext, what: str):
    if not row or (current_user.role != UserRole.sysadmin and row.workspace_id != current_user.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")
    return row


def _checking_or_404(db: Session, account_id: str, current_user: UserContext) -> Account:
    acc = _scoped(db.get(Account, account_id), current_user, "Account")
    if acc.account_type != AccountType.checking:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail="Import de extrato só em conta corrente.")
    if not acc.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Conta inativa.")
    return acc


def _card_or_404(db: Session, card_id: str, current_user: UserContext) -> CreditCardAccount:
    card = _scoped(db.get(CreditCardAccount, card_id), current_user, "Credit card")
    if not card.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Cartão inativo.")
    return card


def _normalize_mime(file: UploadFile) -> str:
    mime = (file.content_type or "").split(";")[0].strip().lower()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext in ("ofx", "qfx"):
        return "application/x-ofx"
    if (not mime or mime in ("application/octet-stream", "binary/octet-stream")) and ext in _EXT_MIME:
        return _EXT_MIME[ext]
    return mime


def _fmt_day(dt: datetime | None) -> str:
    return dt.strftime("%d/%m/%Y") if dt else "—"


def _import(
    db: Session,
    current_user: UserContext,
    file: UploadFile,
    *,
    workspace_id: str,
    source_type: AttachmentSourceType,
    source_id: str,
    hint: ExtractionSourceHint,
):
    payload = file.file.read()  # sync route (threadpool): the LLM call blocks for minutes
    if not payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Arquivo vazio.")
    mime = _normalize_mime(file)
    digest = attachment_storage.content_hash(payload)
    actor = db.get(User, current_user.user_id)
    actor_email = actor.email if actor else current_user.user_id

    # ── dedup camada 1: o mesmo arquivo nunca entra duas vezes ────────────
    att: Attachment | None = None
    prior = db.query(Attachment).filter(
        Attachment.workspace_id == workspace_id,
        Attachment.content_hash == digest,
        Attachment.source_type.in_(_IMPORT_SOURCES),
        Attachment.is_active == True,  # noqa: E712
    ).order_by(Attachment.uploaded_at).all()
    for a in prior:
        jobs = db.query(ExtractionJob).filter(ExtractionJob.attachment_id == a.id).order_by(
            ExtractionJob.created_at.desc(),
        ).all()
        done = next((j for j in jobs if j.status == ExtractionStatus.CONFIRMED), None)
        if done is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Arquivo já importado: \"{a.filename}\", enviado em {_fmt_day(a.uploaded_at)} "
                    f"(anexo {a.id}). Nada a fazer."
                ),
            )
        if any(j.status == ExtractionStatus.RUNNING for j in jobs):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Esse arquivo já está sendo extraído (anexo {a.id}). Aguarde terminar.",
            )
        pending = next((j for j in jobs if j.status == ExtractionStatus.EXTRACTED), None)
        if a.source_type != source_type or a.source_id != source_id:
            if pending is None:
                # Descartado/falhou em outra conta (upload no lugar errado):
                # não segura o arquivo — sobe um anexo novo nesta.
                continue
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Esse arquivo está aguardando revisão em outra conta/cartão: \"{a.filename}\" "
                    f"em {_fmt_day(a.uploaded_at)} (anexo {a.id}). Descarte a revisão lá antes."
                ),
            )
        if pending is not None:
            # Review interrompido — retoma o mesmo job, sem novo custo de LLM.
            return JSONResponse(status_code=status.HTTP_200_OK,
                                content=_out(db, pending, resumed=True).model_dump())
        att = a  # tentativa anterior falhou/foi descartada: reaproveita o arquivo
        break

    if att is None:
        try:
            saved = attachment_storage.save_bytes(workspace_id, payload, mime)
        except attachment_storage.AttachmentMimeNotAllowedError:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Formato não suportado ({mime or 'desconhecido'}). Use OFX, PDF, CSV, XLSX ou imagem.",
            )
        except attachment_storage.AttachmentTooLargeError as exc:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))
        att = Attachment(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            source_type=source_type,
            source_id=source_id,
            kind=saved.kind,
            filename=file.filename or "extrato",
            mime_type=saved.mime_type,
            size_bytes=saved.size_bytes,
            storage_key=saved.storage_key,
            uploaded_at=datetime.now(timezone.utc),
            uploaded_by=current_user.user_id,
            content_hash=digest,
        )
        db.add(att)
        db.flush()
        AuditService(db).log(
            user_email=actor_email,
            action="attachment.uploaded",
            workspace_id=workspace_id,
            user_id=current_user.user_id,
            resource_type="attachment",
            resource_id=att.id,
            details={
                "source_type": source_type.value, "source_id": source_id,
                "filename": att.filename, "size_bytes": att.size_bytes, "content_hash": digest,
            },
        )

    try:
        job = extraction_service.create_and_run(
            db,
            workspace_id=workspace_id,
            attachment_id=att.id,
            source_hint=hint,
            checking_account_id=source_id if source_type == AttachmentSourceType.ACCOUNT else None,
            credit_card_account_id=source_id if source_type == AttachmentSourceType.CREDIT_CARD_ACCOUNT else None,
            user_id=current_user.user_id,
            user_email=actor_email,
        )
    except extraction_service.ExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=_out(db, job).model_dump())


def _history(db: Session, col, source_id: str) -> list[StatementImportOut]:
    jobs = db.query(ExtractionJob).filter(col == source_id).order_by(ExtractionJob.created_at.desc()).limit(100).all()
    return [_out(db, j) for j in jobs]


@router.post("/accounts/{account_id}/statement-imports", response_model=StatementImportOut,
             status_code=status.HTTP_201_CREATED)
def import_statement(
    account_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    acc = _checking_or_404(db, account_id, current_user)
    return _import(
        db, current_user, file, workspace_id=acc.workspace_id,
        source_type=AttachmentSourceType.ACCOUNT, source_id=acc.id,
        hint=ExtractionSourceHint.BANK_STATEMENT,
    )


@router.get("/accounts/{account_id}/statement-imports", response_model=list[StatementImportOut])
def list_statement_imports(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    acc = _scoped(db.get(Account, account_id), current_user, "Account")
    return _history(db, ExtractionJob.checking_account_id, acc.id)


@router.post("/credit-cards/{card_id}/invoice-imports", response_model=StatementImportOut,
             status_code=status.HTTP_201_CREATED)
def import_invoice(
    card_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    card = _card_or_404(db, card_id, current_user)
    return _import(
        db, current_user, file, workspace_id=card.workspace_id,
        source_type=AttachmentSourceType.CREDIT_CARD_ACCOUNT, source_id=card.id,
        hint=ExtractionSourceHint.CARD_INVOICE,
    )


@router.get("/credit-cards/{card_id}/invoice-imports", response_model=list[StatementImportOut])
def list_invoice_imports(
    card_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    card = _scoped(db.get(CreditCardAccount, card_id), current_user, "Credit card")
    return _history(db, ExtractionJob.credit_card_account_id, card.id)
