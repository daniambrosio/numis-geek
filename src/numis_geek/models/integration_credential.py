import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class IntegrationProvider(str, enum.Enum):
    BCB = "BCB"
    BRAPI = "BRAPI"
    FINNHUB = "FINNHUB"
    YFINANCE = "YFINANCE"
    NOTION = "NOTION"
    ANTHROPIC = "ANTHROPIC"   # Spec 38 — LLM extraction


INTEGRATION_PROVIDER_LABELS: dict[IntegrationProvider, str] = {
    IntegrationProvider.BCB: "Banco Central (PTAX)",
    IntegrationProvider.BRAPI: "brapi (B3, FIIs, Tesouro)",
    IntegrationProvider.FINNHUB: "Finnhub (cotação US)",
    IntegrationProvider.YFINANCE: "Yahoo Finance (histórico US)",
    IntegrationProvider.NOTION: "Notion (sync Numis → Notion)",
    IntegrationProvider.ANTHROPIC: "Anthropic Claude (LLM extraction)",
}

PROVIDERS_REQUIRING_CREDENTIALS: set[IntegrationProvider] = {
    IntegrationProvider.BRAPI,
    IntegrationProvider.FINNHUB,
    IntegrationProvider.NOTION,
    IntegrationProvider.ANTHROPIC,
}


class CredentialTestResult(str, enum.Enum):
    UNTESTED = "UNTESTED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class IntegrationCredential(Base):
    """Stored credential for an external integration (token/api key/etc.).

    `workspace_id` is nullable — NULL means system-wide credential managed
    by sysadmin. UI/API only handles system-wide for now; per-workspace
    support is planned but unused in spec 11.

    `secret_value` is stored **plaintext** for the initial local-app phase.
    Before deploying to a remote host (VPS), this must be encrypted at rest
    using Fernet (or equivalent) with a key derived from SECRET_KEY or a
    proper KMS. Tracked in memory `pending_security_spec`.
    """
    __tablename__ = "integration_credential"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workspace.id"), nullable=True
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        Enum(IntegrationProvider), nullable=False
    )
    key_name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # TODO(security-spec): encrypt at rest before VPS deploy. See memory
    # `pending_security_spec`.
    secret_value: Mapped[str] = mapped_column(Text, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_result: Mapped[CredentialTestResult] = mapped_column(
        Enum(CredentialTestResult),
        nullable=False,
        default=CredentialTestResult.UNTESTED,
    )
    last_test_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "provider", "key_name",
            name="ux_cred_ws_provider_key",
        ),
    )
