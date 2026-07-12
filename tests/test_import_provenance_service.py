from __future__ import annotations

from app.models import AudioAsset, Song, SunoTask
from app.services.import_provenance_service import (
    MANUAL_SUNOAPI_IMPORT_SOURCE,
    has_false_manual_sunoapi_import_marker,
    is_confirmed_manual_sunoapi_import,
)
from app.services.music_service import MusicService


class FakeExistingTaskClient:
    async def get_details(self, task_id: str):
        return {
            "code": 200,
            "data": {
                "taskId": task_id,
                "status": "SUCCESS",
                "customMode": True,
                "instrumental": False,
                "response": {
                    "id": f"audio-{task_id}",
                    "title": "Existing Song",
                    "audioUrl": f"https://cdn.example.test/{task_id}.mp3",
                    "duration": 180,
                },
            },
        }


def _local_generation_request() -> dict:
    return {
        "model": "V4_5PLUS",
        "customMode": True,
        "instrumental": False,
        "prompt": "Local lyrics",
        "title": "Local Song",
        "style": "boom bap",
        "callback_url": "http://localhost:8000/api/webhooks/suno",
    }


async def test_duplicate_import_does_not_mark_local_generation_as_manual_import(isolated_db_session):
    task_id = "local-task-duplicate"
    request_payload = _local_generation_request()
    task = SunoTask(
        task_id=task_id,
        task_type="generate_music",
        status="SUCCESS",
        request_payload=dict(request_payload),
        response_payload={"code": 200, "msg": "success", "data": {"taskId": task_id}},
    )
    isolated_db_session.add(task)
    isolated_db_session.flush()

    song = Song(
        title="Local Song",
        task_id=task_id,
        metadata_json={"request_payload": dict(request_payload)},
    )
    asset = AudioAsset(
        task_local_id=task.id,
        song_id=None,
        suno_task_id=task_id,
        audio_id="local-audio-1",
        title="Local Song",
        source_url="https://cdn.example.test/local-audio-1.mp3",
        status="cached",
        metadata_json={"request_payload": dict(request_payload)},
    )
    isolated_db_session.add_all([song, asset])
    isolated_db_session.commit()

    service = MusicService(isolated_db_session, client=FakeExistingTaskClient())
    result = await service.import_external_task(
        {
            "task_id": task_id,
            "task_type": "generate_music",
            "cache_audio": False,
        }
    )

    isolated_db_session.refresh(task)
    isolated_db_session.refresh(song)
    isolated_db_session.refresh(asset)

    assert getattr(result, "already_imported", False) is True
    assert task.request_payload.get("source") != MANUAL_SUNOAPI_IMPORT_SOURCE
    assert song.metadata_json["request_payload"].get("source") != MANUAL_SUNOAPI_IMPORT_SOURCE
    assert asset.metadata_json["request_payload"].get("source") != MANUAL_SUNOAPI_IMPORT_SOURCE
    assert task.request_payload["customMode"] is True
    assert task.request_payload["instrumental"] is False


async def test_duplicate_import_keeps_confirmed_manual_import_marker(isolated_db_session):
    task_id = "manual-import-duplicate"
    task = SunoTask(
        task_id=task_id,
        task_type="generate_music",
        status="SUCCESS",
        request_payload={
            "source": MANUAL_SUNOAPI_IMPORT_SOURCE,
            "task_id": task_id,
            "task_type": "generate_music",
            "cache_audio": False,
        },
        response_payload={
            "source": MANUAL_SUNOAPI_IMPORT_SOURCE,
            "taskId": task_id,
            "taskType": "generate_music",
        },
    )
    isolated_db_session.add(task)
    isolated_db_session.flush()
    asset = AudioAsset(
        task_local_id=task.id,
        suno_task_id=task_id,
        audio_id="manual-audio-1",
        title="Manual Import",
        source_url="https://cdn.example.test/manual-audio-1.mp3",
        status="cached",
        metadata_json={"request_payload": {"source": MANUAL_SUNOAPI_IMPORT_SOURCE}},
    )
    isolated_db_session.add(asset)
    isolated_db_session.commit()

    service = MusicService(isolated_db_session, client=FakeExistingTaskClient())
    await service.import_external_task(
        {
            "task_id": task_id,
            "task_type": "generate_music",
            "cache_audio": False,
        }
    )

    isolated_db_session.refresh(task)
    isolated_db_session.refresh(asset)
    assert task.request_payload["source"] == MANUAL_SUNOAPI_IMPORT_SOURCE
    assert asset.metadata_json["request_payload"]["source"] == MANUAL_SUNOAPI_IMPORT_SOURCE


async def test_recovered_existing_local_asset_uses_neutral_provenance(isolated_db_session):
    task_id = "recovered-local-task"
    request_payload = _local_generation_request()
    asset = AudioAsset(
        suno_task_id=task_id,
        audio_id="recovered-local-audio",
        title="Recovered Local Song",
        source_url="https://cdn.example.test/recovered-local-audio.mp3",
        status="cached",
        metadata_json={"request_payload": dict(request_payload)},
    )
    isolated_db_session.add(asset)
    isolated_db_session.commit()

    service = MusicService(isolated_db_session, client=FakeExistingTaskClient())
    result = await service.import_external_task(
        {
            "task_id": task_id,
            "task_type": "generate_music",
            "cache_audio": False,
        }
    )

    recovered = isolated_db_session.query(SunoTask).filter(SunoTask.task_id == task_id).one()
    isolated_db_session.refresh(asset)
    assert getattr(result, "already_imported", False) is True
    assert recovered.request_payload.get("source") == "existing_library_record"
    assert asset.metadata_json["request_payload"].get("source") != MANUAL_SUNOAPI_IMPORT_SOURCE


def test_false_manual_import_marker_detection_is_conservative():
    local_request = {**_local_generation_request(), "source": MANUAL_SUNOAPI_IMPORT_SOURCE}
    raw_response = {"code": 200, "data": {"taskId": "local-task"}}
    assert has_false_manual_sunoapi_import_marker(
        task_type="generate_music",
        request_payload=local_request,
        response_payload=raw_response,
    )
    assert not is_confirmed_manual_sunoapi_import(
        task_type="generate_music",
        request_payload=local_request,
        response_payload=raw_response,
    )

    manual_response = {"source": MANUAL_SUNOAPI_IMPORT_SOURCE, "taskId": "import-task"}
    assert is_confirmed_manual_sunoapi_import(
        task_type="generate_music",
        request_payload={"source": MANUAL_SUNOAPI_IMPORT_SOURCE},
        response_payload=manual_response,
    )
