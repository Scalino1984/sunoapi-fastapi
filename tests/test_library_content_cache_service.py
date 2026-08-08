"""Regression coverage for Library "Inhalte pruefen".

These tests protect two fragile maintenance contracts:
- generated Replicate cover metadata must become idempotent after one repair;
- imported SunoAPI.org tasks may store original request options in data.param
  as a JSON string, and the backfill must copy those values into local
  request_payload metadata for offline Songdetails display.
"""

import pytest
import json

from app.config import get_settings
from app.models import AudioAsset, AudioProject, Song, StatusNotification, SunoTask
from app.services.library_content_cache_service import _known_cover_urls, _repair_generation_options_from_tasks, _repair_misclassified_local_provider_checks, cache_missing_library_content_once
from app.services.library_ai_tagging_service import normalize_ai_tags
from app.services.music_service import MusicService


@pytest.mark.asyncio
async def test_content_check_restores_local_replicate_cover_from_generate_cover_task(monkeypatch, isolated_db_session):
    db = isolated_db_session
    async def no_provider_backfill(self, *, limit=40):
        return 0

    monkeypatch.setattr(MusicService, "repair_imported_task_generation_options_from_provider", no_provider_backfill)
    settings = get_settings()
    settings.cover_storage_path.mkdir(parents=True, exist_ok=True)
    cover_path = settings.cover_storage_path / "ai_cover_42_song_20260626_120000.jpg"
    cover_path.write_bytes(b"\xff\xd8\xff" + b"replicate-cover" * 16)
    cover_url = f"{settings.suno_cover_public_route.rstrip('/')}/{cover_path.name}"

    project = AudioProject(title="Projekt ohne Cover")
    db.add(project)
    db.flush()
    song = Song(title="Song ohne Cover", project_id=project.id)
    db.add(song)
    db.flush()
    asset = AudioAsset(
        song_id=song.id,
        project_id=project.id,
        source_url="https://cdn.example.test/audio.mp3",
        status="remote",
        title="Song ohne Cover",
    )
    db.add(asset)
    db.flush()
    task = SunoTask(
        task_type="generate_cover_art",
        status="SUCCESS",
        request_payload={"audio_asset_id": asset.id, "song_id": song.id, "backend": "replicate"},
        result_payload={
            "audio_asset_id": asset.id,
            "song_id": song.id,
            "cover_url": cover_url,
            "replicate_source_url": "https://replicate.delivery/example/generated-cover.jpg",
            "model": "pro",
            "title": "Song ohne Cover",
        },
    )
    db.add(task)
    db.commit()

    result = await cache_missing_library_content_once(db, limit=50, notify_always=False)

    db.refresh(asset)
    db.refresh(song)
    db.refresh(project)
    assert result["cover_metadata_fixed"] >= 3
    assert asset.image_url == cover_url
    assert song.cover_image_url == cover_url
    assert project.cover_image_url == cover_url
    assert asset.cover_cached is True
    assert song.cover_cached is True
    assert asset.metadata_json["cover_cache"]["public_url"] == cover_url
    assert asset.metadata_json["cover_cache"]["backend"] == "replicate"
    assert asset.metadata_json["cover_cache"]["replicate_source_url"] == "https://replicate.delivery/example/generated-cover.jpg"
    assert asset.metadata_json["generated_cover"]["backend"] == "replicate"

    second = await cache_missing_library_content_once(db, limit=50, notify_always=False)
    assert second["cover_metadata_fixed"] == 0


def test_known_cover_urls_adds_remote_media_mirror_for_missing_server_cover(monkeypatch, isolated_db_session):
    db = isolated_db_session
    settings = get_settings()
    monkeypatch.setattr(settings, "library_content_remote_media_base_urls", "https://songstudio-react.klangneural.de")
    asset = AudioAsset(
        source_url="manual://local-only",
        image_url="/media/covers/ai_cover_server_only.jpg",
        status="remote",
    )
    db.add(asset)
    db.commit()

    urls = _known_cover_urls(db, asset)

    assert "https://songstudio-react.klangneural.de/media/covers/ai_cover_server_only.jpg" in urls


def test_library_ai_tag_normalization_keeps_tags_compact():
    tags = normalize_ai_tags(["Rap", "rap", "Song", "Deutsch", "Male", "cinematic music", "very long tag name that should be shortened at a sane boundary"], max_tags=4)

    assert tags == ["rap", "german", "male vocal", "cinematic"]


def test_content_check_repairs_imported_sunoapi_generation_options(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_id="task-options-repair",
        task_type="generate_music",
        status="SUCCESS",
        request_payload={"source": "manual_sunoapi_import", "task_id": "task-options-repair"},
        result_payload={
            "data": {
                "param": json.dumps({
                    "negativeTags": "no EDM",
                    "vocalGender": "f",
                    "styleWeight": 0.66,
                    "weirdnessConstraint": 0.22,
                    "audioWeight": 0.44,
                    "customMode": True,
                    "instrumental": False,
                    "personaId": "persona_abc",
                    "personaModel": "style_persona",
                })
            }
        },
    )
    db.add(task)
    db.flush()
    song = Song(task_id="task-options-repair", title="Options Repair", metadata_json={})
    db.add(song)
    db.flush()
    asset = AudioAsset(
        task_local_id=task.id,
        song_id=song.id,
        suno_task_id="task-options-repair",
        source_url="https://cdn.sunoapi.test/options-repair.mp3",
        status="remote",
        metadata_json={"request_payload": {"source": "manual_sunoapi_import"}},
    )
    db.add(asset)
    db.commit()

    changed = _repair_generation_options_from_tasks(db, limit=20)
    db.commit()
    db.refresh(task)
    db.refresh(song)
    db.refresh(asset)

    assert changed == 1
    assert task.request_payload["negativeTags"] == "no EDM"
    assert task.request_payload["vocalGender"] == "f"
    assert task.request_payload["styleWeight"] == 0.66
    assert song.metadata_json["request_payload"]["weirdnessConstraint"] == 0.22
    assert asset.metadata_json["request_payload"]["audioWeight"] == 0.44
    assert asset.metadata_json["request_payload"]["customMode"] is True
    assert asset.metadata_json["request_payload"]["instrumental"] is False
    assert asset.metadata_json["request_payload"]["personaId"] == "persona_abc"
    assert asset.metadata_json["request_payload"]["personaModel"] == "style_persona"


@pytest.mark.asyncio
async def test_provider_generation_option_backfill_retries_old_checked_marker(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_id="task-provider-options-repair",
        task_type="generate_music",
        status="SUCCESS",
        request_payload={
            "source": "manual_sunoapi_import",
            "task_id": "task-provider-options-repair",
            "generation_options_provider_checked": True,
        },
        result_payload={"data": {"status": "SUCCESS"}},
    )
    db.add(task)
    db.flush()
    asset = AudioAsset(
        task_local_id=task.id,
        suno_task_id="task-provider-options-repair",
        source_url="https://cdn.sunoapi.test/provider-options-repair.mp3",
        status="remote",
        metadata_json={"request_payload": {"source": "manual_sunoapi_import"}},
    )
    db.add(asset)
    db.commit()

    class FakeSunoClient:
        async def get_details(self, task_id):
            assert task_id == "task-provider-options-repair"
            return {
                "data": {
                    "taskId": task_id,
                    "param": json.dumps({
                        "negativeTags": "no noise",
                        "vocalGender": "m",
                        "styleWeight": 0.71,
                        "weirdnessConstraint": 0.31,
                        "audioWeight": 0.51,
                        "personaId": "persona_provider",
                        "personaModel": "style_persona",
                    })
                }
            }

    repaired = await MusicService(db, client=FakeSunoClient()).repair_imported_task_generation_options_from_provider(limit=20)
    db.commit()
    db.refresh(task)
    db.refresh(asset)

    assert repaired == 1
    assert task.request_payload["negativeTags"] == "no noise"
    assert task.request_payload["vocalGender"] == "m"
    assert task.request_payload["styleWeight"] == 0.71
    assert task.request_payload["weirdnessConstraint"] == 0.31
    assert task.request_payload["audioWeight"] == 0.51
    assert task.request_payload["personaId"] == "persona_provider"
    assert task.request_payload["personaModel"] == "style_persona"
    assert task.request_payload["generation_options_provider_check_version"] == "sunoapi-options-v4"
    assert asset.metadata_json["request_payload"]["negativeTags"] == "no noise"
    assert asset.metadata_json["request_payload"]["personaId"] == "persona_provider"


@pytest.mark.asyncio
async def test_provider_backfill_never_calls_local_library_content_task(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_id="local-library-content-cache-20260713174326944870",
        task_type="library_content_cache",
        status="SUCCESS",
        request_payload={"limit": 500, "background": True},
        response_payload={"background": True},
        result_payload={"audio_cached": 0, "cover_cached": 0},
    )
    db.add(task)
    db.commit()

    class RejectingClient:
        async def get_details(self, task_id):
            raise AssertionError(f"Local task was sent to provider: {task_id}")

    repaired = await MusicService(db, client=RejectingClient()).repair_imported_task_generation_options_from_provider(limit=20)

    db.refresh(task)
    assert repaired == 0
    assert task.result_payload == {"audio_cached": 0, "cover_cached": 0}
    assert "generation_options_provider_checked" not in task.request_payload


@pytest.mark.asyncio
async def test_provider_backfill_requires_confirmed_manual_import(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_id="provider-generated-by-local-app",
        task_type="generate_music",
        status="SUCCESS",
        request_payload={
            "task_type": "generate_music",
            "callback_url": "http://localhost/api/webhooks/suno",
        },
        response_payload={"code": 200, "data": {"taskId": "provider-generated-by-local-app"}},
        result_payload={"original": "must-stay"},
    )
    db.add(task)
    db.commit()

    class RejectingClient:
        async def get_details(self, task_id):
            raise AssertionError(f"Non-import task was sent to provider backfill: {task_id}")

    repaired = await MusicService(db, client=RejectingClient()).repair_imported_task_generation_options_from_provider(limit=20)

    db.refresh(task)
    assert repaired == 0
    assert task.result_payload == {"original": "must-stay"}


@pytest.mark.asyncio
async def test_provider_backfill_preserves_task_result_status_and_type(isolated_db_session):
    db = isolated_db_session
    original_result = {"data": {"status": "SUCCESS", "audio": "stored-result"}}
    task = SunoTask(
        task_id="manual-provider-preserve",
        task_type="generate_music",
        status="SUCCESS",
        request_payload={
            "source": "manual_sunoapi_import",
            "task_id": "manual-provider-preserve",
            "task_type": "generate_music",
        },
        response_payload={
            "source": "manual_sunoapi_import",
            "taskId": "manual-provider-preserve",
            "taskType": "generate_music",
        },
        result_payload=original_result,
    )
    db.add(task)
    db.commit()

    class FakeClient:
        async def get_details(self, task_id):
            return {
                "code": 200,
                "data": {
                    "taskId": task_id,
                    "param": json.dumps({"negativeTags": "no noise", "styleWeight": 0.8}),
                },
            }

    repaired = await MusicService(db, client=FakeClient()).repair_imported_task_generation_options_from_provider(limit=20)

    db.refresh(task)
    assert repaired == 1
    assert task.task_type == "generate_music"
    assert task.status == "SUCCESS"
    assert task.result_payload == original_result
    assert task.request_payload["negativeTags"] == "no noise"
    assert task.request_payload["styleWeight"] == 0.8


@pytest.mark.asyncio
async def test_provider_backfill_rejects_empty_or_gateway_placeholder_response(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_id="manual-provider-empty",
        task_type="generate_music",
        status="SUCCESS",
        request_payload={
            "source": "manual_sunoapi_import",
            "task_id": "manual-provider-empty",
            "task_type": "generate_music",
        },
        response_payload={
            "source": "manual_sunoapi_import",
            "taskId": "manual-provider-empty",
            "taskType": "generate_music",
        },
        result_payload={"original": True},
    )
    db.add(task)
    db.commit()

    class EmptyClient:
        async def get_details(self, task_id):
            return {"code": 200, "msg": "success", "data": None}

    repaired = await MusicService(db, client=EmptyClient()).repair_imported_task_generation_options_from_provider(limit=20)

    db.refresh(task)
    assert repaired == 0
    assert task.result_payload == {"original": True}
    assert "generation_options_provider_checked" not in task.request_payload


@pytest.mark.asyncio
async def test_unknown_task_type_has_no_default_music_record_info_fallback(isolated_db_session):
    class RejectingClient:
        async def get_details(self, task_id):
            raise AssertionError("Unknown task type must not fall back to generate/record-info")

    service = MusicService(isolated_db_session, client=RejectingClient())
    with pytest.raises(ValueError, match="Kein freigegebener SunoAPI-Record-Info-Endpunkt"):
        await service._fetch_external_task_details("external-id", "library_content_cache")


def test_content_check_repairs_previous_local_provider_pollution(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(
        task_id="local-library-content-cache-20260713174326944870",
        task_type="library_content_cache",
        status="success",
        request_payload={
            "limit": 500,
            "background": True,
            "generation_options_provider_checked": True,
            "generation_options_provider_checked_at": "2026-07-13T17:58:29",
            "generation_options_provider_check_version": "sunoapi-options-v3",
        },
        response_payload={
            "last_debug_event": {
                "event": "library_content_cache_finished",
                "data": {"audio_cached": 0, "cover_cached": 0, "stale_metadata_fixed": 1},
            }
        },
        result_payload={"code": 200, "msg": "success", "data": None},
    )
    db.add(task)
    db.flush()
    db.add(StatusNotification(
        event_type="library_content_background_loaded",
        title="Neue Inhalte wurden geladen",
        message="Neue Inhalte wurden geladen",
        severity="success",
        status="unread",
        task_local_id=task.id,
        suno_task_id=task.task_id,
        content_type="system",
        content_id=task.id,
        target_tab="library",
        target_payload={"audio_cached": 0, "cover_cached": 0, "stale_metadata_fixed": 1},
    ))
    db.commit()

    repaired = _repair_misclassified_local_provider_checks(db)

    db.refresh(task)
    assert repaired == 1
    assert task.status == "SUCCESS"
    assert task.result_payload == {"audio_cached": 0, "cover_cached": 0, "stale_metadata_fixed": 1}
    assert "generation_options_provider_checked" not in task.request_payload
    assert "generation_options_provider_checked_at" not in task.request_payload
    assert "generation_options_provider_check_version" not in task.request_payload
