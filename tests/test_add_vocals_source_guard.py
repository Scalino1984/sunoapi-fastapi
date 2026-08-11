from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import AudioAsset
from app.routers.archive import _asset_instrumental_status, _assert_add_vocals_source_is_safe
from app.routers.music import add_vocals
from app.schemas import AddVocalsRequest, ArchiveAudioAddVocalsRequest


def _asset(metadata: dict | None) -> AudioAsset:
    return AudioAsset(source_url="https://cdn.example.test/source.mp3", status="remote", metadata_json=metadata)


def test_add_vocals_guard_uses_saved_instrumental_generation_flag():
    assert _asset_instrumental_status(_asset({"request_payload": {"instrumental": True}})) is True
    assert _asset_instrumental_status(_asset({"request_payload": {"instrumental": False}})) is False
    assert _asset_instrumental_status(_asset({"request_payload": {"instrumental": "true"}})) is True


def test_add_vocals_guard_blocks_known_vocal_asset_even_when_confirmed():
    with pytest.raises(HTTPException, match="wurde mit Vocals erzeugt") as exc_info:
        _assert_add_vocals_source_is_safe(_asset({"request_payload": {"instrumental": False}}), source_is_instrumental=True)
    assert exc_info.value.status_code == 422


def test_add_vocals_guard_requires_confirmation_only_for_unknown_asset():
    unknown_asset = _asset({"candidate": {"prompt": "legacy asset"}})
    with pytest.raises(HTTPException, match="nicht gespeichert"):
        _assert_add_vocals_source_is_safe(unknown_asset, source_is_instrumental=False)
    _assert_add_vocals_source_is_safe(unknown_asset, source_is_instrumental=True)


def test_add_vocals_confirmation_uses_local_alias_and_is_not_a_suno_field():
    payload = {
        "uploadUrl": "https://cdn.example.test/instrumental.mp3",
        "prompt": "smooth German soul vocals",
        "title": "Backing Track Vocals",
        "negativeTags": "distorted, off key",
        "style": "soul",
        "sourceIsInstrumental": True,
    }
    assert AddVocalsRequest.model_validate(payload).model_dump(by_alias=True)["sourceIsInstrumental"] is True
    archive_payload = {key: value for key, value in payload.items() if key != "uploadUrl"}
    assert ArchiveAudioAddVocalsRequest.model_validate(archive_payload).model_dump(by_alias=True)["sourceIsInstrumental"] is True


async def test_direct_add_vocals_route_requires_confirmation_and_strips_local_field(monkeypatch):
    forwarded: dict = {}

    class FakeMusicService:
        def __init__(self, db):
            assert db == "test-db"

        async def call_task_endpoint(self, task_type, payload):
            forwarded["task_type"] = task_type
            forwarded["payload"] = payload
            return {"ok": True}

    monkeypatch.setattr("app.routers.music.MusicService", FakeMusicService)
    request = AddVocalsRequest.model_validate({
        "uploadUrl": "https://cdn.example.test/instrumental.mp3",
        "prompt": "smooth German soul vocals",
        "title": "Backing Track Vocals",
        "negativeTags": "distorted, off key",
        "style": "soul",
        "sourceIsInstrumental": True,
    })
    assert await add_vocals(request, db="test-db") == {"ok": True}
    assert forwarded == {
        "task_type": "add_vocals",
        "payload": {
            "uploadUrl": "https://cdn.example.test/instrumental.mp3",
            "prompt": "smooth German soul vocals",
            "title": "Backing Track Vocals",
            "negativeTags": "distorted, off key",
            "style": "soul",
            "model": "V4_5PLUS",
        },
    }

    with pytest.raises(HTTPException, match="bestätige diese Quelle"):
        await add_vocals(request.model_copy(update={"source_is_instrumental": False}), db="test-db")
