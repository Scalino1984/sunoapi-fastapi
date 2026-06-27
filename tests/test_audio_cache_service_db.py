from types import SimpleNamespace

import pytest

from app.models import AudioAsset, Song, SunoTask
from app.services.audio_cache_service import AudioCacheService, AudioCandidate


def _service(db, *, cache_mode="off"):
    service = AudioCacheService(db)
    service.settings = SimpleNamespace(
        suno_audio_cache_mode=cache_mode,
        local_content_storage_enabled=True,
        suno_auto_download_only_music=True,
        suno_audio_allowed_extensions_list=[".mp3", ".wav", ".m4a"],
    )
    return service


@pytest.mark.asyncio
async def test_cache_task_audio_materializes_remote_assets_even_when_download_is_off(isolated_db_session):
    db = isolated_db_session
    task = SunoTask(task_id="task-remote", task_type="generate_music", status="SUCCESS", request_payload={"title": "Remote Song"})
    db.add(task)
    db.commit()

    assets = await _service(db, cache_mode="off").cache_task_audio(task)

    assert len(assets) == 0

    task.result_payload = {
        "data": [{"id": "audio-1", "title": "Remote Song", "audioUrl": "https://cdn.example.test/remote-song.mp3"}]
    }
    db.commit()
    assets = await _service(db, cache_mode="off").cache_task_audio(task)

    assert len(assets) == 1
    assert assets[0].status == "remote"
    assert assets[0].audio_id == "audio-1"
    assert assets[0].display_title == "Remote Song"


def test_get_or_create_asset_reuses_existing_asset_by_audio_id_and_keeps_identity(isolated_db_session):
    db = isolated_db_session
    song = Song(title="Song Meta", task_id="task-1")
    task = SunoTask(task_id="task-1", task_type="extend_music", status="SUCCESS", request_payload={"audio_id": "parent-a"})
    existing = AudioAsset(audio_id="clip-1", source_url="https://cdn.example.test/old.mp3", status="remote")
    db.add_all([song, task, existing])
    db.commit()

    candidate = AudioCandidate(
        source_url="https://cdn.example.test/new.mp3",
        audio_id="clip-1",
        title="Extended Take",
        image_url="https://cdn.example.test/cover.jpg",
        duration_seconds=88,
        metadata={"audioUrl": "https://cdn.example.test/new.mp3"},
    )

    asset = _service(db)._get_or_create_asset(candidate, task=task, song=song)

    assert asset.id == existing.id
    assert asset.task_local_id == task.id
    assert asset.song_id == song.id
    assert asset.suno_task_id == "task-1"
    assert asset.image_url == "https://cdn.example.test/cover.jpg"
    assert asset.operation_label == "Extended"
    assert asset.parent_audio_id == "parent-a"


def test_get_or_create_asset_records_deleted_match_without_restoring_deleted_asset(isolated_db_session):
    db = isolated_db_session
    deleted = AudioAsset(audio_id="clip-deleted", source_url="https://cdn.example.test/deleted.mp3", status="remote", is_deleted=True)
    db.add(deleted)
    db.commit()

    asset = _service(db)._get_or_create_asset(
        AudioCandidate(source_url="https://cdn.example.test/deleted.mp3", audio_id="clip-deleted", title="Reimport"),
        task=None,
        song=None,
    )

    assert asset.id != deleted.id
    assert asset.is_deleted is False
    assert asset.metadata_json["recreated_from_deleted_match"] is True
