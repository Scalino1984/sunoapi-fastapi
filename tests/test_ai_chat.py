from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-ai-chat-tests-only")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ai_chat.sqlite3")
os.environ.setdefault("ALLOW_REGISTRATION", "true")
os.environ.setdefault("SUNO_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app

client = TestClient(app)


def setup_module() -> None:
    db_file = Path("test_ai_chat.sqlite3")
    if db_file.exists():
        db_file.unlink()
    Base.metadata.create_all(bind=engine)
    client.post("/auth/register", json={"email": "ai@example.com", "password": "very-secure-password"})


def teardown_module() -> None:
    engine.dispose()
    db_file = Path("test_ai_chat.sqlite3")
    if db_file.exists():
        db_file.unlink()


def auth_headers() -> dict[str, str]:
    response = client.post("/auth/login", json={"email": "ai@example.com", "password": "very-secure-password"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_ai_chat_config_requires_auth() -> None:
    client.cookies.clear()
    response = client.get("/api/ai-chat/config")
    assert response.status_code == 401


def test_ai_chat_config_with_auth() -> None:
    response = client.get("/api/ai-chat/config", headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert "openai" in body["allowed_models"]
    assert "GPT-5.4-mini" in body["allowed_models"]["openai"]


def test_ai_chat_session_create_and_undo_redo() -> None:
    headers = auth_headers()
    created = client.post(
        "/api/ai-chat/sessions",
        headers=headers,
        json={"title": "Test Canvas", "provider": "openai", "model": "GPT-5.4-mini", "canvas_content": "[Verse 1]\nTest"},
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    saved = client.post(
        f"/api/ai-chat/sessions/{session_id}/canvas",
        headers=headers,
        json={"canvas_content": "[Verse 1]\nTest neu", "source": "manual"},
    )
    assert saved.status_code == 200
    undo = client.post(f"/api/ai-chat/sessions/{session_id}/undo", headers=headers)
    assert undo.status_code == 200
    assert undo.json()["canvas_content"] == "[Verse 1]\nTest"
    redo = client.post(f"/api/ai-chat/sessions/{session_id}/redo", headers=headers)
    assert redo.status_code == 200
    assert redo.json()["canvas_content"] == "[Verse 1]\nTest neu"


def test_global_assistant_context_help() -> None:
    response = client.post(
        "/api/assistant/chat",
        headers=auth_headers(),
        json={
            "message": "Was ist der nächste Schritt?",
            "app_context": {"active_tab": "lyrics", "page_label": "Songtext Studio", "current_canvas": "[Hook]\nTest"},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "reply" in body
    assert any(action["id"] == "lyrics_suno_ready" for action in body["suggested_actions"])
