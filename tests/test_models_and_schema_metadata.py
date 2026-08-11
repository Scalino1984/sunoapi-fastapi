from app.models import AudioAsset, Song, SunoTask
from app.routers.archive import mark_audio_asset_played
from app.schemas import AudioAssetRead, SongRead, TaskRead
from app.services.replicate_cover_service import ReplicateCoverService


def test_audio_asset_properties_read_candidate_and_request_payload_fallbacks():
    asset = AudioAsset(
        id=1,
        source_url="https://cdn.example.test/song.mp3",
        status="remote",
        image_url="https://cdn.example.test/image.jpg",
        operation_label="Generiert",
        has_been_played=False,
        metadata_json={
            "candidate": {
                "lyrics": "Candidate Lyrics",
                "tags": "Boom Bap",
                "modelName": "V5_5",
                "sourceAudioUrl": "https://cdn.example.test/src.mp3",
                "streamAudioUrl": "https://cdn.example.test/stream.mp3",
                "imageUrl": "https://cdn.example.test/candidate.jpg",
            },
            "request_payload": {"prompt": "Request Prompt"},
            "cover_cache": {"public_url": "/media/covers/local.jpg", "source_url": "https://cdn.example.test/source.jpg"},
            "import_source": "suno_public_clip",
            "generation_source": "sunoapi",
        },
    )

    data = AudioAssetRead.model_validate(asset).model_dump()

    assert data["prompt"] == "Request Prompt"
    assert data["lyrics"] == "Candidate Lyrics"
    assert data["style"] == "Boom Bap"
    assert data["model_name"] == "V5_5"
    assert data["source_audio_url"] == "https://cdn.example.test/src.mp3"
    assert data["stream_audio_url"] == "https://cdn.example.test/stream.mp3"
    assert data["cover_local_url"] == "/media/covers/local.jpg"
    assert data["cover_cached"] is True
    assert data["operation_type"] == "Generiert"
    assert data["has_been_played"] is False


def test_audio_asset_played_status_is_persisted_on_successful_playback(isolated_db_session):
    asset = AudioAsset(
        source_url="https://cdn.example.test/new-song.mp3",
        status="remote",
        has_been_played=False,
    )
    isolated_db_session.add(asset)
    isolated_db_session.commit()

    result = mark_audio_asset_played(asset.id, db=isolated_db_session)

    isolated_db_session.refresh(asset)
    assert result == {"ok": True, "audio_asset_id": asset.id, "has_been_played": True}
    assert asset.has_been_played is True


def test_song_read_exposes_capabilities_and_cover_cache_context():
    song = Song(
        id=2,
        title="Song",
        task_id="task-1",
        cover_image_url="https://cdn.example.test/cover.jpg",
        metadata_json={
            "capabilities": {"local_playback": True, "sunoapi_extend": False},
            "cover_cache": {"public_url": "/media/covers/song.jpg", "source_url": "https://cdn.example.test/source.jpg"},
            "import_source": "manual",
            "generation_source": "opencli",
        },
    )

    data = SongRead.model_validate(song).model_dump()

    assert data["capabilities"]["local_playback"] is True
    assert data["cover_local_url"] == "/media/covers/song.jpg"
    assert data["cover_cached"] is True
    assert data["import_source"] == "manual"
    assert data["generation_source"] == "opencli"


def test_suno_task_progress_is_mapped_and_exposed_for_local_cover_tasks(isolated_db_session):
    db = isolated_db_session
    asset = AudioAsset(
        source_url="https://cdn.example.test/song.mp3",
        title="Cover Test",
        status="cached",
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)

    task = ReplicateCoverService(db).create_status_task(asset, model="pro", note="snow", has_reference=True)
    data = TaskRead.model_validate(task).model_dump()

    assert task.task_type == "generate_cover_art"
    assert task.progress == 0
    assert data["progress"] == 0
    assert data["request_payload"]["has_reference"] is True
