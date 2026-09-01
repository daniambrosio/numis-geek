import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.asset import Asset
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.services import fi_logo_storage
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/financial-institutions", tags=["financial-institutions"])


# ── schemas ───────────────────────────────────────────────────────────────────

class FinancialInstitutionOut(BaseModel):
    id: str
    long_name: str
    short_name: str
    logo_slug: str | None
    brand_color: str | None
    has_logo: bool
    country: str
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, fi: FinancialInstitution) -> "FinancialInstitutionOut":
        return cls(
            id=fi.id,
            long_name=fi.long_name,
            short_name=fi.short_name,
            logo_slug=fi.logo_slug,
            brand_color=fi.brand_color,
            has_logo=bool(fi.logo_storage_key),
            country=fi.country,
            is_active=fi.is_active,
            created_at=fi.created_at.isoformat(),
            updated_at=fi.updated_at.isoformat(),
        )


class FinancialInstitutionLogoOut(BaseModel):
    """Item da listagem de logos consumida pelo `<FILogo>` do frontend.

    `data_url` vem embutido porque a API é autenticada via Bearer e `<img src>`
    não manda header — sem isso o logo exigiria endpoint público.
    """

    id: str
    logo_slug: str | None
    short_name: str
    brand_color: str | None
    data_url: str | None


class FinancialInstitutionRequest(BaseModel):
    long_name: str
    short_name: str
    logo_slug: str | None = None
    brand_color: str | None = None  # #RRGGBB
    country: str = "BR"  # ISO-2


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_sysadmin(current_user: UserContext) -> None:
    if current_user.role != UserRole.sysadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SysAdmin only.")


def _get_or_404(db: Session, fi_id: str) -> FinancialInstitution:
    fi = db.get(FinancialInstitution, fi_id)
    if not fi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Financial institution not found.")
    return fi


def _parse_color(value: str | None) -> str | None:
    try:
        return fi_logo_storage.normalize_hex_color(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[FinancialInstitutionOut])
def list_financial_institutions(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    items = db.query(FinancialInstitution).filter(FinancialInstitution.is_active == True).order_by(FinancialInstitution.short_name).all()  # noqa: E712
    return [FinancialInstitutionOut.from_orm(fi) for fi in items]


@router.get("/logos", response_model=list[FinancialInstitutionLogoOut])
def list_financial_institution_logos(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Logos + cores de marca de TODAS as instituições (inclusive inativas —
    telas históricas ainda renderizam o logo delas). Qualquer usuário
    autenticado lê; escrita continua sysadmin-only."""
    items = db.query(FinancialInstitution).order_by(FinancialInstitution.short_name).all()
    out: list[FinancialInstitutionLogoOut] = []
    for fi in items:
        url = (
            fi_logo_storage.data_url(fi.logo_storage_key, fi.logo_mime or "image/png")
            if fi.logo_storage_key
            else None
        )
        out.append(
            FinancialInstitutionLogoOut(
                id=fi.id,
                logo_slug=fi.logo_slug,
                short_name=fi.short_name,
                brand_color=fi.brand_color,
                data_url=url,
            )
        )
    return out


@router.post("", response_model=FinancialInstitutionOut, status_code=status.HTTP_201_CREATED)
def create_financial_institution(
    body: FinancialInstitutionRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name=body.long_name,
        short_name=body.short_name,
        logo_slug=body.logo_slug,
        brand_color=_parse_color(body.brand_color),
        country=body.country,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(fi)
    db.flush()
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action="financial_institution.created",
        resource_type="financial_institution",
        resource_id=fi.id,
        details={"short_name": fi.short_name},
    )
    return FinancialInstitutionOut.from_orm(fi)


@router.put("/{fi_id}", response_model=FinancialInstitutionOut)
def update_financial_institution(
    fi_id: str,
    body: FinancialInstitutionRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    fi = _get_or_404(db, fi_id)
    fi.long_name = body.long_name
    fi.short_name = body.short_name
    fi.logo_slug = body.logo_slug
    fi.brand_color = _parse_color(body.brand_color)
    fi.country = body.country
    fi.updated_at = datetime.now(timezone.utc)
    fi.updated_by = current_user.user_id
    db.flush()
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action="financial_institution.updated",
        resource_type="financial_institution",
        resource_id=fi.id,
        details={"short_name": fi.short_name},
    )
    return FinancialInstitutionOut.from_orm(fi)


@router.post("/{fi_id}/logo", response_model=FinancialInstitutionOut)
async def upload_financial_institution_logo(
    fi_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Substitui o logo da instituição. Um arquivo por instituição — o
    anterior é apagado do disco quando a extensão muda."""
    _require_sysadmin(current_user)
    fi = _get_or_404(db, fi_id)

    payload = await file.read()
    mime = file.content_type or ""
    try:
        saved = fi_logo_storage.save_bytes(fi.id, payload, mime)
    except fi_logo_storage.LogoMimeNotAllowedError:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Formato '{mime or 'desconhecido'}' não suportado. "
                f"Use PNG, JPG, WEBP ou SVG."
            ),
        )
    except fi_logo_storage.LogoTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        )

    previous_key = fi.logo_storage_key
    if previous_key and previous_key != saved.storage_key:
        fi_logo_storage.delete(previous_key)

    fi.logo_storage_key = saved.storage_key
    fi.logo_mime = saved.mime_type
    fi.updated_at = datetime.now(timezone.utc)
    fi.updated_by = current_user.user_id
    db.flush()

    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action="financial_institution.logo_uploaded",
        resource_type="financial_institution",
        resource_id=fi.id,
        details={
            "short_name": fi.short_name,
            "filename": file.filename,
            "mime_type": saved.mime_type,
            "size_bytes": saved.size_bytes,
        },
    )
    return FinancialInstitutionOut.from_orm(fi)


@router.delete("/{fi_id}/logo", response_model=FinancialInstitutionOut)
def delete_financial_institution_logo(
    fi_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Remove o logo — a instituição volta a renderizar iniciais sobre a cor
    de marca."""
    _require_sysadmin(current_user)
    fi = _get_or_404(db, fi_id)
    previous_key = fi.logo_storage_key
    if previous_key:
        fi_logo_storage.delete(previous_key)
    fi.logo_storage_key = None
    fi.logo_mime = None
    fi.updated_at = datetime.now(timezone.utc)
    fi.updated_by = current_user.user_id
    db.flush()

    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action="financial_institution.logo_removed",
        resource_type="financial_institution",
        resource_id=fi.id,
        details={"short_name": fi.short_name, "storage_key": previous_key},
    )
    return FinancialInstitutionOut.from_orm(fi)


@router.put("/{fi_id}/deactivate", response_model=FinancialInstitutionOut)
def deactivate_financial_institution(
    fi_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    fi = _get_or_404(db, fi_id)
    # RESTRICT: cannot deactivate while any active asset's account references this FI.
    from numis_geek.models.account import Account
    referencing_active_assets = db.query(Asset).join(
        Account, Asset.account_id == Account.id,
    ).filter(
        Account.financial_institution_id == fi.id,
        Asset.is_active == True,  # noqa: E712
    ).first()
    if referencing_active_assets:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate: there are active assets referencing this institution.",
        )
    fi.is_active = False
    fi.updated_at = datetime.now(timezone.utc)
    fi.updated_by = current_user.user_id
    db.flush()
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action="financial_institution.deactivated",
        resource_type="financial_institution",
        resource_id=fi.id,
        details={"short_name": fi.short_name},
    )
    return FinancialInstitutionOut.from_orm(fi)
