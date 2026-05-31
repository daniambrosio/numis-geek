"""Sysadmin routes for integration credentials (brapi, Finnhub tokens, etc.)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.integrations.bcb import BCBError, fetch_ptax_range
from numis_geek.models.integration_credential import (
    INTEGRATION_PROVIDER_LABELS,
    PROVIDERS_REQUIRING_CREDENTIALS,
    CredentialTestResult,
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.models.user import User, UserRole
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/sysadmin/integrations", tags=["integrations"])


# ── schemas ───────────────────────────────────────────────────────────────────

class IntegrationCredentialOut(BaseModel):
    id: str
    provider: str
    provider_label: str
    key_name: str
    label: str | None
    secret_preview: str  # masked: '••••' + last 4 chars
    is_active: bool
    last_tested_at: str | None
    last_test_result: str
    last_test_message: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, c: IntegrationCredential) -> "IntegrationCredentialOut":
        tail = c.secret_value[-4:] if c.secret_value and len(c.secret_value) >= 4 else c.secret_value or ""
        return cls(
            id=c.id,
            provider=c.provider.value,
            provider_label=INTEGRATION_PROVIDER_LABELS.get(c.provider, c.provider.value),
            key_name=c.key_name,
            label=c.label,
            secret_preview=f"••••{tail}" if tail else "••••",
            is_active=c.is_active,
            last_tested_at=c.last_tested_at.isoformat() if c.last_tested_at else None,
            last_test_result=c.last_test_result.value,
            last_test_message=c.last_test_message,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )


class IntegrationCredentialRequest(BaseModel):
    provider: IntegrationProvider
    key_name: str
    label: str | None = None
    secret_value: str


class IntegrationCredentialPatch(BaseModel):
    label: str | None = None
    secret_value: str | None = None
    is_active: bool | None = None


class ProviderCatalogEntry(BaseModel):
    provider: str
    label: str
    requires_credentials: bool


class TestResultOut(BaseModel):
    result: str
    message: str
    tested_at: str


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_sysadmin(current_user: UserContext) -> None:
    if current_user.role != UserRole.sysadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SysAdmin only.")


def _get_or_404(db: Session, cred_id: str) -> IntegrationCredential:
    c = db.get(IntegrationCredential, cred_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found.")
    return c


def _test_provider(provider: IntegrationProvider, secret_value: str) -> tuple[CredentialTestResult, str]:
    """Ping the provider to verify credentials. BCB+YFINANCE return SUCCESS
    without using the secret (no creds required)."""
    if provider == IntegrationProvider.BCB:
        try:
            from datetime import date, timedelta
            rows = fetch_ptax_range(date.today() - timedelta(days=14), date.today())
            return CredentialTestResult.SUCCESS, f"OK — {len(rows)} rows returned"
        except BCBError as e:
            return CredentialTestResult.FAILED, str(e)
    if provider == IntegrationProvider.YFINANCE:
        return CredentialTestResult.SUCCESS, "No credentials required."
    if provider == IntegrationProvider.BRAPI:
        try:
            import httpx
            r = httpx.get(
                "https://brapi.dev/api/quote/PETR4",
                params={"token": secret_value},
                timeout=15.0,
            )
            if r.status_code == 200 and r.json().get("results"):
                return CredentialTestResult.SUCCESS, "OK"
            return CredentialTestResult.FAILED, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return CredentialTestResult.FAILED, f"{type(e).__name__}: {e}"
    if provider == IntegrationProvider.FINNHUB:
        try:
            import httpx
            r = httpx.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": "AAPL", "token": secret_value},
                timeout=15.0,
            )
            if r.status_code == 200 and "c" in r.json():
                return CredentialTestResult.SUCCESS, "OK"
            return CredentialTestResult.FAILED, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return CredentialTestResult.FAILED, f"{type(e).__name__}: {e}"
    if provider == IntegrationProvider.ANTHROPIC:
        # Spec 38/48 — ping the Messages endpoint with a cheap 1-token call.
        try:
            import httpx
            r = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": secret_value,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                timeout=15.0,
            )
            if r.status_code == 200:
                return CredentialTestResult.SUCCESS, "OK"
            return CredentialTestResult.FAILED, f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return CredentialTestResult.FAILED, f"{type(e).__name__}: {e}"

    return CredentialTestResult.FAILED, f"Unknown provider {provider}"


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/providers", response_model=list[ProviderCatalogEntry])
def list_providers(
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    return [
        ProviderCatalogEntry(
            provider=p.value,
            label=INTEGRATION_PROVIDER_LABELS[p],
            requires_credentials=p in PROVIDERS_REQUIRING_CREDENTIALS,
        )
        for p in IntegrationProvider
    ]


@router.get("", response_model=list[IntegrationCredentialOut])
def list_credentials(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    rows = (
        db.query(IntegrationCredential)
        .filter(IntegrationCredential.workspace_id.is_(None))
        .order_by(IntegrationCredential.provider, IntegrationCredential.key_name)
        .all()
    )
    return [IntegrationCredentialOut.from_orm(c) for c in rows]


@router.post("", response_model=IntegrationCredentialOut, status_code=status.HTTP_201_CREATED)
def create_credential(
    body: IntegrationCredentialRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    now = datetime.now(timezone.utc)
    existing = (
        db.query(IntegrationCredential)
        .filter(
            IntegrationCredential.workspace_id.is_(None),
            IntegrationCredential.provider == body.provider,
            IntegrationCredential.key_name == body.key_name,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Credential with this provider + key_name already exists.",
        )
    c = IntegrationCredential(
        id=str(uuid.uuid4()),
        workspace_id=None,
        provider=body.provider,
        key_name=body.key_name,
        label=body.label,
        secret_value=body.secret_value,
        is_active=True,
        last_test_result=CredentialTestResult.UNTESTED,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(c)
    db.flush()
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action="integration_credential.created",
        resource_type="integration_credential",
        resource_id=c.id,
        details={"provider": body.provider.value, "key_name": body.key_name},
    )
    return IntegrationCredentialOut.from_orm(c)


@router.patch("/{cred_id}", response_model=IntegrationCredentialOut)
def update_credential(
    cred_id: str,
    body: IntegrationCredentialPatch,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    c = _get_or_404(db, cred_id)
    if body.label is not None:
        c.label = body.label
    if body.secret_value is not None:
        c.secret_value = body.secret_value
        c.last_tested_at = None
        c.last_test_result = CredentialTestResult.UNTESTED
        c.last_test_message = None
    if body.is_active is not None:
        c.is_active = body.is_active
    c.updated_at = datetime.now(timezone.utc)
    c.updated_by = current_user.user_id
    db.flush()
    return IntegrationCredentialOut.from_orm(c)


@router.delete("/{cred_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(
    cred_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    c = _get_or_404(db, cred_id)
    db.delete(c)
    db.flush()
    return None


@router.post("/{cred_id}/test", response_model=TestResultOut)
def test_credential(
    cred_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    c = _get_or_404(db, cred_id)
    result, message = _test_provider(c.provider, c.secret_value)
    now = datetime.now(timezone.utc)
    c.last_tested_at = now
    c.last_test_result = result
    c.last_test_message = message[:500]
    c.updated_at = now
    db.flush()
    return TestResultOut(result=result.value, message=message, tested_at=now.isoformat())
