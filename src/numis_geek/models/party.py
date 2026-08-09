"""Spec 68 — Party (fornecedor/cliente) + PartyAlias.

Party is the counterpart of a transaction ("Pão de Açúcar", "Cliente
Consultoria X"). Optional on transactions; auto-created by the statement
import (spec 71) from the normalized description. PartyAlias maps each
raw normalized description string to its party — the exact-match lookup
the import uses, and the thing that survives a manual merge.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class PartyKind(str, enum.Enum):
    SUPPLIER = "SUPPLIER"
    CLIENT = "CLIENT"
    BOTH = "BOTH"


class Party(Base):
    __tablename__ = "party"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[PartyKind] = mapped_column(Enum(PartyKind), nullable=False, default=PartyKind.SUPPLIER)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_party_workspace_name", "workspace_id", "name"),
    )


class PartyAlias(Base):
    __tablename__ = "party_alias"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    party_id: Mapped[str] = mapped_column(String(36), ForeignKey("party.id"), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ux_party_alias_ws_alias", "workspace_id", "alias_normalized", unique=True),
        Index("ix_party_alias_party", "party_id"),
    )
