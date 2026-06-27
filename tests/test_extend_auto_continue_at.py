import pytest

from app.models import AppSetting, AudioAsset, SunoTask
from app.routers.archive import _apply_auto_continue_at_for_archive_extend
from app.routers.archive import _run_auto_continue_at_analysis_for_asset
from app.services.extend_continue_at_analysis_service import (
    AI_SETTINGS_KEY,
    ExtendContinueAtAnalysisResult,
    load_extend_continue_at_settings,
)
from app.services.music_service import MusicService


def test_extend_auto_continue_at_admin_settings_default_disabled(isolated_db_session):
    settings = load_extend_continue_at_settings(isolated_db_session)

    assert settings.enabled is False
    assert settings.search_window_seconds == 15
    assert settings.vocal_threshold_ratio == 0.03
    assert settings.fallback_offset_seconds == 4.0


def test_archive_auto_continue_at_disabled_keeps_manual_value(isolated_db_session):
    isolated_db_session.add(AppSetting(key=AI_SETTINGS_KEY, value={"extend_auto_continue_at_enabled": False}))
    isolated_db_session.commit()
    asset = AudioAsset(id=10, title="Original", audio_id="audio-source-1", source_url="https://example.test/audio.mp3")
    payload = {"autoContinueAt": True, "continueAt": 60}

    result = _apply_auto_continue_at_for_archive_extend(isolated_db_session, asset, payload)

    assert result is None
    assert payload["continueAt"] == 60
    assert "autoContinueAt" not in payload


def test_archive_auto_continue_at_enabled_overwrites_continue_at(monkeypatch, isolated_db_session):
    isolated_db_session.add(AppSetting(key=AI_SETTINGS_KEY, value={"extend_auto_continue_at_enabled": True}))
    isolated_db_session.commit()
    asset = AudioAsset(id=11, title="Original", audio_id="audio-source-1", source_url="https://example.test/audio.mp3")
    payload = {"autoContinueAt": True, "continueAt": 60}

    def fake_analyze(asset_arg, settings_arg):
        assert asset_arg is asset
        assert settings_arg.enabled is True
        return ExtendContinueAtAnalysisResult(
            continue_at=137.42,
            method="test",
            confidence=0.9,
            reason="unit test",
            duration_seconds=140,
            search_window_seconds=15,
        )

    monkeypatch.setattr("app.routers.archive.analyze_continue_at_for_asset", fake_analyze)

    result = _apply_auto_continue_at_for_archive_extend(isolated_db_session, asset, payload)

    assert payload["continueAt"] == 137.42
    assert "autoContinueAt" not in payload
    assert result["continue_at"] == 137.42


def test_archive_analysis_helper_returns_result_without_payload(monkeypatch, isolated_db_session):
    isolated_db_session.add(AppSetting(key=AI_SETTINGS_KEY, value={"extend_auto_continue_at_enabled": True}))
    isolated_db_session.commit()
    asset = AudioAsset(id=12, title="Original", audio_id="audio-source-1", source_url="https://example.test/audio.mp3")

    monkeypatch.setattr(
        "app.routers.archive.analyze_continue_at_for_asset",
        lambda asset_arg, settings_arg: ExtendContinueAtAnalysisResult(
            continue_at=88.5,
            method="test",
            confidence=0.9,
            reason="unit test",
            duration_seconds=100,
            search_window_seconds=15,
        ),
    )

    result = _run_auto_continue_at_analysis_for_asset(isolated_db_session, asset)

    assert result["continue_at"] == 88.5
    assert result["method"] == "test"


class FakeExtendClient:
    def __init__(self):
        self.extend_payload = None

    async def extend_music(self, payload):
        self.extend_payload = dict(payload)
        return {"code": 200, "data": {"taskId": "task-auto-extend"}}

    async def upload_and_cover(self, payload):
        raise AssertionError("unexpected")

    async def upload_and_extend(self, payload):
        raise AssertionError("unexpected")

    async def add_instrumental(self, payload):
        raise AssertionError("unexpected")

    async def add_vocals(self, payload):
        raise AssertionError("unexpected")

    async def boost_music_style(self, payload):
        raise AssertionError("unexpected")

    async def generate_mashup(self, payload):
        raise AssertionError("unexpected")

    async def replace_section(self, payload):
        raise AssertionError("unexpected")

    async def generate_persona(self, payload):
        raise AssertionError("unexpected")

    async def create_music_cover(self, payload):
        raise AssertionError("unexpected")

    async def generate_sounds(self, payload):
        raise AssertionError("unexpected")

    async def get_timestamped_lyrics(self, payload):
        raise AssertionError("unexpected")

    async def separate(self, payload):
        raise AssertionError("unexpected")

    async def convert_to_wav(self, payload):
        raise AssertionError("unexpected")

    async def generate_midi(self, payload):
        raise AssertionError("unexpected")

    async def create_video(self, payload):
        raise AssertionError("unexpected")

    async def generate_voice_verification_phrase(self, payload):
        raise AssertionError("unexpected")

    async def regenerate_voice_verification_phrase(self, payload):
        raise AssertionError("unexpected")

    async def create_custom_voice(self, payload):
        raise AssertionError("unexpected")


@pytest.mark.asyncio
async def test_music_service_does_not_forward_auto_continue_at_to_suno(isolated_db_session):
    client = FakeExtendClient()
    service = MusicService(isolated_db_session, client=client)

    await service.call_task_endpoint(
        "extend_music",
        {
            "audioId": "audio-source-1",
            "defaultParamFlag": True,
            "title": "Extended",
            "prompt": "Text",
            "style": "Style",
            "continueAt": 137.42,
        },
    )

    assert client.extend_payload["continueAt"] == 137.42
    assert "autoContinueAt" not in client.extend_payload
    task = isolated_db_session.query(SunoTask).one()
    assert task.request_payload["continueAt"] == 137.42
    assert "autoContinueAt" not in task.request_payload
