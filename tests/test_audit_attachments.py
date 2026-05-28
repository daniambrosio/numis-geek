"""Spec 43 §3 — orphan/ghost audit CLI tests.

Exercises the pure `audit()` function with a controlled FS + DB state.
We don't shell out to the CLI itself — `render()` is tested separately.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.attachment import (
    Attachment, AttachmentKind, AttachmentSourceType,
)
from scripts.audit_attachments import audit, render


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
    yield s
    # Clean up rows between tests so the audit is deterministic.
    s.query(Attachment).delete()
    s.commit()
    s.close()


def _att(workspace_id: str, storage_key: str) -> Attachment:
    return Attachment(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        source_type=AttachmentSourceType.ASSET,
        source_id=str(uuid.uuid4()),
        kind=AttachmentKind.IMAGE,
        filename=Path(storage_key).name,
        mime_type="image/png",
        size_bytes=42,
        storage_key=storage_key,
        is_active=True,
        uploaded_at=datetime.now(timezone.utc),
        uploaded_by=None,
    )


def _seed_pair(tmp_root: Path, session, workspace_id: str, name: str) -> None:
    """Create file on disk AND matching Attachment row."""
    ws_dir = tmp_root / workspace_id
    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / name).write_bytes(b"\x89PNG\r\n\x1a\n payload")
    session.add(_att(workspace_id, f"{workspace_id}/{name}"))
    session.commit()


def test_audit_reports_zero_when_in_sync(tmp_path, session):
    _seed_pair(tmp_path, session, "ws-a", "ok.png")
    result = audit(session, tmp_path)
    assert result.fs_count == 1
    assert result.db_count == 1
    assert result.orphan_files == []
    assert result.ghost_rows == []
    assert result.has_mismatch is False


def test_audit_detects_orphan_file_on_fs(tmp_path, session):
    """A file lives on disk but no Attachment row points at it."""
    ws_dir = tmp_path / "ws-a"
    ws_dir.mkdir(parents=True)
    (ws_dir / "orphan.png").write_bytes(b"abcd")

    result = audit(session, tmp_path)
    assert result.fs_count == 1
    assert result.db_count == 0
    assert [p.name for p in result.orphan_files] == ["orphan.png"]
    assert result.ghost_rows == []
    assert result.has_mismatch is True


def test_audit_detects_ghost_row_missing_file(tmp_path, session):
    """A row exists but its file is gone (e.g. user `rm`'d the workspace dir)."""
    session.add(_att("ws-a", "ws-a/gone.png"))
    session.commit()

    result = audit(session, tmp_path)
    assert result.fs_count == 0
    assert result.db_count == 1
    assert result.orphan_files == []
    assert len(result.ghost_rows) == 1
    assert result.ghost_rows[0].storage_key == "ws-a/gone.png"
    assert result.has_mismatch is True


def test_audit_mixed_state(tmp_path, session):
    """Realistic mix: 1 ok pair, 1 orphan file, 1 ghost row."""
    _seed_pair(tmp_path, session, "ws-a", "ok.png")
    (tmp_path / "ws-a" / "orphan.png").write_bytes(b"xx")
    session.add(_att("ws-b", "ws-b/missing.png"))
    session.commit()

    result = audit(session, tmp_path)
    assert result.fs_count == 2  # ok.png + orphan.png
    assert result.db_count == 2  # ok + missing
    assert [p.name for p in result.orphan_files] == ["orphan.png"]
    assert [r.storage_key for r in result.ghost_rows] == ["ws-b/missing.png"]


def test_audit_handles_missing_root_dir(tmp_path, session):
    """If ROOT doesn't exist, treat as zero files — not an error."""
    ghost_root = tmp_path / "does-not-exist"
    result = audit(session, ghost_root)
    assert result.fs_count == 0
    assert result.db_count == 0
    assert result.has_mismatch is False


def test_render_contains_sync_marker_when_clean(tmp_path, session):
    _seed_pair(tmp_path, session, "ws-a", "ok.png")
    text = render(audit(session, tmp_path))
    assert "FS and DB are in sync" in text


def test_render_lists_orphans_and_ghosts(tmp_path, session):
    _seed_pair(tmp_path, session, "ws-a", "ok.png")
    (tmp_path / "ws-a" / "orphan.png").write_bytes(b"xx")
    session.add(_att("ws-b", "ws-b/missing.png"))
    session.commit()
    text = render(audit(session, tmp_path))
    assert "Orphan files" in text
    assert "orphan.png" in text
    assert "Ghost rows" in text
    assert "ws-b/missing.png" in text
