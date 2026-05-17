import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.asset import Asset
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/financial-institutions", tags=["financial-institutions"])


# ── schemas ───────────────────────────────────────────────────────────────────

class FinancialInstitutionOut(BaseModel):
    id: str
    long_name: str
    short_name: str
    logo_slug: str | None
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
            is_active=fi.is_active,
            created_at=fi.created_at.isoformat(),
            updated_at=fi.updated_at.isoformat(),
        )


class FinancialInstitutionRequest(BaseModel):
    long_name: str
    short_name: str
    logo_slug: str | None = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_sysadmin(current_user: UserContext) -> None:
    if current_user.role != UserRole.sysadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SysAdmin only.")


def _get_or_404(db: Session, fi_id: str) -> FinancialInstitution:
    fi = db.get(FinancialInstitution, fi_id)
    if not fi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Financial institution not found.")
    return fi


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[FinancialInstitutionOut])
def list_financial_institutions(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    items = db.query(FinancialInstitution).filter(FinancialInstitution.is_active == True).order_by(FinancialInstitution.short_name).all()  # noqa: E712
    return [FinancialInstitutionOut.from_orm(fi) for fi in items]


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
