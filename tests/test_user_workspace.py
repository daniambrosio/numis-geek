from datetime import datetime, timedelta, timezone

import jwt
import pytest

from numis_geek.config import SECRET_KEY
from numis_geek.exceptions import AuthError
from numis_geek.exceptions import PermissionError
from numis_geek.models.user import UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_workspace(db, name="Test Workspace"):
    svc = WorkspaceService(db)
    return svc.create(name)


def make_user(db, workspace_id, email="admin@example.com", password="secret", role=UserRole.admin):
    svc = UserService(db)
    return svc.create(workspace_id, email, password, role)


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

def test_create_workspace(db):
    ws = make_workspace(db)
    assert ws.id is not None
    assert ws.name == "Test Workspace"
    assert ws.created_at is not None


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

def test_create_user(db):
    ws = make_workspace(db, "WS")
    user = make_user(db, ws.id)
    assert user.id is not None
    assert user.email == "admin@example.com"
    assert user.password_hash != "secret"
    assert user.role == UserRole.admin
    assert user.is_active is True


# ---------------------------------------------------------------------------
# Auth — login
# ---------------------------------------------------------------------------

def test_login_success(db):
    ws = make_workspace(db, "WS2")
    make_user(db, ws.id, email="user@example.com", password="pass123")

    token = AuthService(db).login("user@example.com", "pass123")
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])

    assert payload["role"] == UserRole.admin.value
    assert payload["workspace_id"] == ws.id


def test_login_wrong_password(db):
    ws = make_workspace(db, "WS3")
    make_user(db, ws.id, email="a@example.com", password="correct")

    with pytest.raises(AuthError):
        AuthService(db).login("a@example.com", "wrong")


def test_login_unknown_email(db):
    with pytest.raises(AuthError):
        AuthService(db).login("nobody@example.com", "whatever")


def test_login_inactive_user(db):
    ws = make_workspace(db, "WS4")
    user = make_user(db, ws.id, email="inactive@example.com", password="pass")
    user.is_active = False
    db.flush()

    with pytest.raises(AuthError):
        AuthService(db).login("inactive@example.com", "pass")


# ---------------------------------------------------------------------------
# Auth — token verification
# ---------------------------------------------------------------------------

def test_token_verification(db):
    ws = make_workspace(db, "WS5")
    make_user(db, ws.id, email="verify@example.com", password="pass")

    token = AuthService(db).login("verify@example.com", "pass")
    ctx = AuthService.verify_token(token)

    assert ctx.role == UserRole.admin
    assert ctx.workspace_id == ws.id


def test_token_expired(db):
    expired_payload = {
        "sub": "some-id",
        "workspace_id": "some-ws",
        "role": "admin",
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    expired_token = jwt.encode(expired_payload, SECRET_KEY, algorithm="HS256")

    with pytest.raises(AuthError):
        AuthService.verify_token(expired_token)


# ---------------------------------------------------------------------------
# Roles / permissions
# ---------------------------------------------------------------------------

def test_member_cannot_invite(db):
    ws = make_workspace(db, "WS6")
    member = make_user(db, ws.id, email="member@example.com", role=UserRole.member)

    with pytest.raises(PermissionError):
        UserService(db).invite(ws.id, "new@example.com", "pass", acting_user=member)


def test_admin_can_invite(db):
    ws = make_workspace(db, "WS7")
    admin = make_user(db, ws.id, email="admin2@example.com")

    new_user = UserService(db).invite(ws.id, "invited@example.com", "pass", acting_user=admin)
    assert new_user.email == "invited@example.com"
    assert new_user.role == UserRole.member
