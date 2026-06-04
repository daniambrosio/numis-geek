"""Spec 54 — testes do endpoint /version + módulo de versão."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from numis_geek.api.app import app
from numis_geek.version import get_version_info


@pytest.fixture
def client():
    return TestClient(app)


def test_version_module_returns_three_keys():
    info = get_version_info()
    assert set(info.keys()) == {"version", "sha", "date"}
    assert isinstance(info["version"], str) and info["version"]
    assert isinstance(info["sha"], str) and info["sha"]
    assert isinstance(info["date"], str) and info["date"]


def test_version_module_honors_env_vars(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "fakesha7")
    monkeypatch.setenv("BUILD_DATE", "2026-01-15")
    info = get_version_info()
    assert info["sha"] == "fakesha7"
    assert info["date"] == "2026-01-15"


def test_version_module_dev_fallback_when_no_env(monkeypatch):
    # Sem env vars, sha vem do git, date vem de date.today().
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILD_DATE", raising=False)
    info = get_version_info()
    # 'unknown' rola se o subprocess git falhar (sandbox sem git, p.ex.).
    assert info["sha"] != ""
    assert len(info["date"]) == 10  # YYYY-MM-DD


def test_version_endpoint_root_path(client):
    r = client.get("/version")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"version", "sha", "date"}


def test_version_endpoint_api_prefix(client):
    # Em produção a requisição chega como /api/version (sem strip do
    # Vite). Mesmo handler, dois paths registrados.
    r = client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"version", "sha", "date"}


def test_version_endpoint_is_public(client):
    # Banner roda antes do login — endpoint não pode exigir auth.
    r = client.get("/version", headers={})
    assert r.status_code == 200
