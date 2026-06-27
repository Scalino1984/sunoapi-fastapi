from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.models import AudioAsset, AudioTranscript, Base, Song, SunoTask
from app.routers.library import _delete_audio_asset
from app.services.music_service import MusicService


@pytest.fixture()
def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=True, autocommit=False)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_deleting_last_audio_for_suno_task_soft_deletes_task_id(_session):
    db = _session
    task = SunoTask(task_id="task-123", task_type="generate_music", status="SUCCESS")
    song_a = Song(title="Variante A", task_id="task-123")
    song_b = Song(title="Variante B", task_id="task-123")
    db.add_all([task, song_a, song_b])
    db.flush()

    asset_a = AudioAsset(
        task_local_id=task.id,
        song_id=song_a.id,
        suno_task_id="task-123",
        audio_id="audio-a",
        title="Variante A",
        source_url="https://example.test/audio-a.mp3",
        status="cached",
    )
    asset_b = AudioAsset(
        task_local_id=task.id,
        song_id=song_b.id,
        suno_task_id="task-123",
        audio_id="audio-b",
        title="Variante B",
        source_url="https://example.test/audio-b.mp3",
        status="cached",
    )
    db.add_all([asset_a, asset_b])
    db.commit()

    assert _delete_audio_asset(db, asset_a.id, delete_file=False, reason="Test") is True
    db.flush()
    assert db.get(AudioAsset, asset_a.id).is_deleted is True
    assert db.get(Song, song_a.id).is_deleted is True
    assert db.get(SunoTask, task.id).is_deleted is False

    assert _delete_audio_asset(db, asset_b.id, delete_file=False, reason="Test") is True
    db.flush()
    assert db.get(AudioAsset, asset_b.id).is_deleted is True
    assert db.get(Song, song_b.id).is_deleted is True
    assert db.get(SunoTask, task.id).is_deleted is True


def test_import_dedupe_ignores_orphaned_finished_task(_session):
    db = _session
    task = SunoTask(task_id="task-orphan", task_type="generate_music", status="SUCCESS")
    db.add(task)
    db.commit()

    existing = MusicService(db)._find_existing_imported_task("task-orphan")

    assert existing is None
    assert db.get(SunoTask, task.id).is_deleted is True


def test_import_dedupe_keeps_running_orphaned_task(_session):
    db = _session
    task = SunoTask(task_id="task-running", task_type="generate_music", status="RUNNING")
    db.add(task)
    db.commit()

    existing = MusicService(db)._find_existing_imported_task("task-running")

    assert existing is not None
    assert existing.id == task.id
    assert db.get(SunoTask, task.id).is_deleted is False


def test_soft_delete_without_files_reassigns_transcripts_to_same_audio_replacement(_session):
    db = _session
    old_asset = AudioAsset(
        audio_id="audio-same",
        title="Alte Zeile",
        source_url="https://example.test/audio-same.mp3",
        status="cached",
    )
    replacement = AudioAsset(
        audio_id="audio-same",
        title="Aktive Ersatz-Zeile",
        source_url="https://example.test/audio-same.mp3",
        status="cached",
    )
    db.add_all([old_asset, replacement])
    db.flush()
    transcript = AudioTranscript(
        audio_asset_id=old_asset.id,
        backend="groq",
        language="de",
        status="completed",
        srt_text="1\n00:00:00,000 --> 00:00:01,000\nTest\n",
    )
    db.add(transcript)
    db.commit()

    assert _delete_audio_asset(db, old_asset.id, delete_file=False, reason="Test") is True
    db.flush()

    assert db.get(AudioAsset, old_asset.id).is_deleted is True
    updated = db.get(AudioTranscript, transcript.id)
    assert updated.audio_asset_id == replacement.id
    assert updated.status == "completed"


def test_soft_delete_without_files_archives_transcripts_without_replacement(_session):
    db = _session
    asset = AudioAsset(
        audio_id="audio-without-replacement",
        title="Einzelne Zeile",
        source_url="https://example.test/audio-without-replacement.mp3",
        status="cached",
    )
    db.add(asset)
    db.flush()
    transcript = AudioTranscript(
        audio_asset_id=asset.id,
        backend="groq",
        language="de",
        status="completed",
        srt_text="1\n00:00:00,000 --> 00:00:01,000\nTest\n",
    )
    db.add(transcript)
    db.commit()

    assert _delete_audio_asset(db, asset.id, delete_file=False, reason="Test") is True
    db.flush()

    assert db.get(AudioAsset, asset.id).is_deleted is True
    updated = db.get(AudioTranscript, transcript.id)
    assert updated.audio_asset_id == asset.id
    assert updated.status == "archived_orphan"
    assert "kein eindeutiger aktiver Ersatz" in updated.error_message
