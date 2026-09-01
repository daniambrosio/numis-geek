import uuid
from datetime import datetime, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.api.app import app
from numis_geek.api.deps import get_db
from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService

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


def override_get_db():
    db = TestSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def seed():
    db = TestSession()

    ws = WorkspaceService(db).create("IF Test WS")
    admin = UserService(db).create(ws.id, "if_admin@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="sysadmin@test.internal",
        name="SysAdmin",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)
    db.commit()

    db.refresh(ws)
    db.refresh(admin)
    db.refresh(sysadmin)

    admin_token = AuthService(db).login("if_admin@test.com", "adminpass")
    sysadmin_token = AuthService(db).login("sysadmin@test.internal", "syspass")

    ws_id = ws.id
    admin_id = admin.id
    sysadmin_id = sysadmin.id
    db.close()

    return {
        "ws_id": ws_id,
        "admin_id": admin_id,
        "sysadmin_id": sysadmin_id,
        "admin_token": admin_token,
        "sysadmin_token": sysadmin_token,
    }


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_list_empty_authenticated(client, seed):
    r = client.get("/api/financial-institutions", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_fi_sysadmin(client, seed):
    r = client.post("/api/financial-institutions", json={
        "long_name": "Banco Teste S.A.",
        "short_name": "Teste",
        "logo_slug": "teste",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201
    data = r.json()
    assert data["long_name"] == "Banco Teste S.A."
    assert data["short_name"] == "Teste"
    assert data["is_active"] is True
    seed["fi_id"] = data["id"]


def test_create_fi_admin_forbidden(client, seed):
    r = client.post("/api/financial-institutions", json={
        "long_name": "Not Allowed",
        "short_name": "NA",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 403


def test_list_shows_created(client, seed):
    r = client.get("/api/financial-institutions", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    short_names = [fi["short_name"] for fi in r.json()]
    assert "Teste" in short_names


def test_update_fi(client, seed):
    fi_id = seed["fi_id"]
    r = client.put(f"/api/financial-institutions/{fi_id}", json={
        "long_name": "Banco Teste Atualizado S.A.",
        "short_name": "Teste2",
        "logo_slug": "teste2",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 200
    assert r.json()["short_name"] == "Teste2"


def test_deactivate_fi(client, seed):
    fi_id = seed["fi_id"]
    r = client.put(f"/api/financial-institutions/{fi_id}/deactivate", headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_deactivated_excluded_from_list(client, seed):
    r = client.get("/api/financial-institutions", headers=auth(seed["admin_token"]))
    ids = [fi["id"] for fi in r.json()]
    assert seed["fi_id"] not in ids


def test_deactivate_admin_forbidden(client, seed):
    # Create a fresh IF to try to deactivate
    r_create = client.post("/api/financial-institutions", json={
        "long_name": "Banco Guard",
        "short_name": "Guard",
    }, headers=auth(seed["sysadmin_token"]))
    fi_id = r_create.json()["id"]
    r = client.put(f"/api/financial-institutions/{fi_id}/deactivate", headers=auth(seed["admin_token"]))
    assert r.status_code == 403


# ── Spec 19: country (ISO-2) ─────────────────────────────────────────────────

def test_create_fi_with_country(client, seed):
    r = client.post("/api/financial-institutions", json={
        "long_name": "Avenue Securities",
        "short_name": "Avenue-T",
        "country": "US",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201
    assert r.json()["country"] == "US"


def test_country_defaults_to_br_when_omitted(client, seed):
    r = client.post("/api/financial-institutions", json={
        "long_name": "Banco BR S.A.",
        "short_name": "BR-Default",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201
    assert r.json()["country"] == "BR"


def test_update_changes_country(client, seed):
    r = client.post("/api/financial-institutions", json={
        "long_name": "Some FI",
        "short_name": "Some-FI",
        "country": "BR",
    }, headers=auth(seed["sysadmin_token"]))
    fi_id = r.json()["id"]
    r2 = client.put(f"/api/financial-institutions/{fi_id}", json={
        "long_name": "Some FI",
        "short_name": "Some-FI",
        "country": "US",
    }, headers=auth(seed["sysadmin_token"]))
    assert r2.status_code == 200
    assert r2.json()["country"] == "US"


# ── Logo próprio + cor de marca ──────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def logo_root(tmp_path_factory):
    """Isola o storage de logos num tmpdir — nada é escrito em ./data."""
    from numis_geek.services import fi_logo_storage

    original = fi_logo_storage.ROOT
    fi_logo_storage.ROOT = tmp_path_factory.mktemp("fi-logos")
    yield fi_logo_storage.ROOT
    fi_logo_storage.ROOT = original


@pytest.fixture
def logo_fi(client, seed):
    r = client.post("/api/financial-institutions", json={
        "long_name": "Banco Logo S.A.",
        "short_name": "Logo-FI",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201
    return r.json()["id"]


def _png(size: int = 64) -> bytes:
    # O conteúdo não é validado (só o MIME do multipart) — basta ser bytes.
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


def test_create_fi_without_logo_has_no_logo(client, seed, logo_fi):
    r = client.get("/api/financial-institutions", headers=auth(seed["admin_token"]))
    fi = next(x for x in r.json() if x["id"] == logo_fi)
    assert fi["has_logo"] is False
    assert fi["brand_color"] is None


def test_upload_logo_sysadmin(client, seed, logo_fi, logo_root):
    r = client.post(
        f"/api/financial-institutions/{logo_fi}/logo",
        files={"file": ("logo.png", _png(), "image/png")},
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 200
    assert r.json()["has_logo"] is True
    assert (logo_root / f"{logo_fi}.png").exists()


def test_uploaded_logo_shows_in_logos_index(client, seed, logo_fi):
    client.post(
        f"/api/financial-institutions/{logo_fi}/logo",
        files={"file": ("logo.png", _png(), "image/png")},
        headers=auth(seed["sysadmin_token"]),
    )
    # Qualquer usuário autenticado lê a listagem — o FILogo do app precisa dela.
    r = client.get("/api/financial-institutions/logos", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    row = next(x for x in r.json() if x["id"] == logo_fi)
    assert row["data_url"].startswith("data:image/png;base64,")


def test_upload_logo_admin_forbidden(client, seed, logo_fi):
    r = client.post(
        f"/api/financial-institutions/{logo_fi}/logo",
        files={"file": ("logo.png", _png(), "image/png")},
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 403


def test_upload_logo_rejects_disallowed_mime(client, seed, logo_fi):
    r = client.post(
        f"/api/financial-institutions/{logo_fi}/logo",
        files={"file": ("logo.txt", b"not an image", "text/plain")},
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 415


def test_upload_logo_rejects_oversized_file(client, seed, logo_fi):
    from numis_geek.services import fi_logo_storage

    payload = b"\x00" * (fi_logo_storage.MAX_BYTES + 1)
    r = client.post(
        f"/api/financial-institutions/{logo_fi}/logo",
        files={"file": ("big.png", payload, "image/png")},
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 413


def test_replacing_logo_with_other_format_drops_old_file(client, seed, logo_fi, logo_root):
    client.post(
        f"/api/financial-institutions/{logo_fi}/logo",
        files={"file": ("logo.png", _png(), "image/png")},
        headers=auth(seed["sysadmin_token"]),
    )
    r = client.post(
        f"/api/financial-institutions/{logo_fi}/logo",
        files={"file": ("logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")},
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 200
    assert (logo_root / f"{logo_fi}.svg").exists()
    assert not (logo_root / f"{logo_fi}.png").exists()


def test_delete_logo(client, seed, logo_fi, logo_root):
    client.post(
        f"/api/financial-institutions/{logo_fi}/logo",
        files={"file": ("logo.png", _png(), "image/png")},
        headers=auth(seed["sysadmin_token"]),
    )
    r = client.delete(
        f"/api/financial-institutions/{logo_fi}/logo",
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 200
    assert r.json()["has_logo"] is False
    assert not (logo_root / f"{logo_fi}.png").exists()

    logos = client.get("/api/financial-institutions/logos", headers=auth(seed["admin_token"])).json()
    assert next(x for x in logos if x["id"] == logo_fi)["data_url"] is None


def test_delete_logo_admin_forbidden(client, seed, logo_fi):
    r = client.delete(
        f"/api/financial-institutions/{logo_fi}/logo",
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 403


def test_brand_color_is_normalized_lowercase(client, seed):
    r = client.post("/api/financial-institutions", json={
        "long_name": "Nubank Cor",
        "short_name": "Nu-Cor",
        "brand_color": "#820AD1",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201
    assert r.json()["brand_color"] == "#820ad1"


def test_brand_color_rejects_invalid_hex(client, seed):
    r = client.post("/api/financial-institutions", json={
        "long_name": "Cor Ruim",
        "short_name": "Cor-Ruim",
        "brand_color": "roxo",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 400


def test_brand_color_cleared_on_update(client, seed):
    r = client.post("/api/financial-institutions", json={
        "long_name": "Cor Temp",
        "short_name": "Cor-Temp",
        "brand_color": "#123456",
    }, headers=auth(seed["sysadmin_token"]))
    fi_id = r.json()["id"]
    r2 = client.put(f"/api/financial-institutions/{fi_id}", json={
        "long_name": "Cor Temp",
        "short_name": "Cor-Temp",
        "brand_color": "",
    }, headers=auth(seed["sysadmin_token"]))
    assert r2.status_code == 200
    assert r2.json()["brand_color"] is None


def test_logos_index_requires_auth(client):
    r = client.get("/api/financial-institutions/logos")
    assert r.status_code in (401, 403)


def test_logo_upload_is_audited(client, seed, logo_fi):
    client.post(
        f"/api/financial-institutions/{logo_fi}/logo",
        files={"file": ("logo.png", _png(), "image/png")},
        headers=auth(seed["sysadmin_token"]),
    )
    r = client.get(
        "/api/audit?action=financial_institution.logo_uploaded",
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 200
    entries = r.json()["items"]
    assert any(e["resource_id"] == logo_fi for e in entries)
