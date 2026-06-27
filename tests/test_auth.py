from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-auth-tests-only")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth.sqlite3")
os.environ.setdefault("ALLOW_REGISTRATION", "false")
os.environ.setdefault("SUNO_API_KEY", "test")

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Base, engine
from app.main import app

client = TestClient(app)


def setup_module() -> None:
    db_file = Path("test_auth.sqlite3")
    if db_file.exists():
        db_file.unlink()
    Base.metadata.create_all(bind=engine)


def teardown_module() -> None:
    engine.dispose()
    db_file = Path("test_auth.sqlite3")
    if db_file.exists():
        db_file.unlink()


def set_registration(value: str | None) -> None:
    os.environ["ALLOW_REGISTRATION"] = "false" if value is None else value
    get_settings.cache_clear()


def test_registration_disabled_false() -> None:
    set_registration("false")
    response = client.post("/auth/register", json={"email": "blocked@example.com", "password": "very-secure-password"})
    assert response.status_code == 403
    assert response.json() == {"detail": "Registration is currently disabled."}


def test_registration_disabled_missing() -> None:
    set_registration(None)
    response = client.post("/auth/register", json={"email": "missing@example.com", "password": "very-secure-password"})
    assert response.status_code == 403
    assert response.json() == {"detail": "Registration is currently disabled."}


def test_registration_enabled_login_and_me() -> None:
    set_registration("true")
    response = client.post("/auth/register", json={"email": "admin@example.com", "password": "very-secure-password"})
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "admin@example.com"
    assert "hashed_password" not in body

    login = client.post("/auth/login", json={"email": "admin@example.com", "password": "very-secure-password"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    assert token

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "admin@example.com"


def test_invalid_login() -> None:
    response = client.post("/auth/login", json={"email": "admin@example.com", "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials."


def test_protected_endpoint_without_token() -> None:
    client.cookies.clear()
    response = client.get("/api/music/runtime-config")
    assert response.status_code == 401


def test_protected_endpoint_with_invalid_token() -> None:
    client.cookies.clear()
    response = client.get("/api/music/runtime-config", headers={"Authorization": "Bearer invalid-token"})
    assert response.status_code == 401


def test_protected_endpoint_with_valid_token() -> None:
    login = client.post("/auth/login", json={"email": "admin@example.com", "password": "very-secure-password"})
    token = login.json()["access_token"]
    response = client.get("/api/music/runtime-config", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert "models" in response.json()
