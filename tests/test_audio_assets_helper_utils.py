from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from app.routers.audio_assets import (
    _delete_audio_file_content,
    _delete_cover_content,
    _path_from_public_url,
    _public_url_for_storage_file,
    _resolve_file_inside_roots,
    _safe_zip_part,
    _sanitize_upload_stem,
    _validate_upload_extension,
    _write_upload_file,
)
from app.models import AudioAsset, AudioProject, Song


def test_upload_name_and_zip_part_sanitizers_are_stable():
    assert _sanitize_upload_stem("  Donnerbalken 4?! / Mix  ") == "Donnerbalken_4_____Mix"
    assert _sanitize_upload_stem("***", fallback="audio") == "audio"
    assert _safe_zip_part("Song: 1 / Final?!") == "Song__1___Final"


def test_validate_upload_extension_accepts_only_allowed_extensions():
    assert _validate_upload_extension("song.MP3", [".mp3", ".wav"], "Audio") == ".mp3"
    with pytest.raises(HTTPException) as exc:
        _validate_upload_extension("song.exe", [".mp3"], "Audio")
    assert exc.value.status_code == 422


def test_public_url_and_path_resolution_are_confined_to_storage_root(tmp_path):
    storage = tmp_path / "storage" / "audio"
    storage.mkdir(parents=True)
    audio = storage / "song.mp3"
    audio.write_bytes(b"audio")

    assert _public_url_for_storage_file(audio, storage, "/media/audio") == "/media/audio/song.mp3"
    assert _path_from_public_url("/media/audio/song.mp3", "/media/audio", storage) == storage / "song.mp3"
    assert _path_from_public_url("/media/audio/../secret.mp3", "/media/audio", storage) is None
    assert _resolve_file_inside_roots(str(audio), [storage]) == audio.resolve()
    assert _resolve_file_inside_roots(str(tmp_path / "outside.mp3"), [storage]) is None


def test_write_upload_file_hashes_content_and_rejects_empty_or_too_large_files(tmp_path):
    target = tmp_path / "upload.mp3"
    upload = UploadFile(filename="upload.mp3", file=BytesIO(b"abc"), headers={"content-type": "audio/mpeg"})
    size, digest = _write_upload_file(upload, target, 10)

    assert size == 3
    assert target.read_bytes() == b"abc"
    assert len(digest) == 64

    with pytest.raises(HTTPException) as too_large:
        _write_upload_file(UploadFile(filename="big.mp3", file=BytesIO(b"abcdef")), tmp_path / "big.mp3", 3)
    assert too_large.value.status_code == 413

    with pytest.raises(HTTPException) as empty:
        _write_upload_file(UploadFile(filename="empty.mp3", file=BytesIO(b"")), tmp_path / "empty.mp3", 10)
    assert empty.value.status_code == 422


def test_delete_audio_file_keeps_shared_local_file(monkeypatch, isolated_db_session, tmp_path):
    db = isolated_db_session
    audio_root = tmp_path / "audio"
    audio_root.mkdir()
    audio_file = audio_root / "shared.mp3"
    audio_file.write_bytes(b"shared-audio")
    public_url = "/media/audio/shared.mp3"

    from app.routers import audio_assets as audio_assets_router

    monkeypatch.setattr(
        audio_assets_router,
        "get_settings",
        lambda: type("Settings", (), {"audio_storage_path": audio_root})(),
    )

    first = AudioAsset(
        source_url="https://example.test/first.mp3",
        local_path=str(audio_file),
        public_url=public_url,
        filename="shared.mp3",
        status="cached",
    )
    second = AudioAsset(
        source_url="https://example.test/second.mp3",
        local_path=str(audio_file),
        public_url=public_url,
        filename="shared.mp3",
        status="cached",
    )
    db.add_all([first, second])
    db.commit()

    result = _delete_audio_file_content(db, first)

    assert result["shared_reference"] is True
    assert result["removed_files"] == 0
    assert audio_file.exists()
    assert first.local_path is None
    assert second.local_path == str(audio_file)


def test_delete_cover_keeps_shared_local_cover(monkeypatch, isolated_db_session, tmp_path):
    db = isolated_db_session
    cover_root = tmp_path / "covers"
    cover_root.mkdir()
    cover_file = cover_root / "shared.webp"
    cover_file.write_bytes(b"shared-cover")
    public_url = "/media/covers/shared.webp"

    from app.routers import audio_assets as audio_assets_router

    monkeypatch.setattr(
        audio_assets_router,
        "get_settings",
        lambda: type("Settings", (), {"cover_storage_path": cover_root, "suno_cover_public_route": "/media/covers"})(),
    )

    song = Song(title="Song", cover_image_url=public_url)
    project = AudioProject(title="Projekt", cover_image_url=public_url)
    first = AudioAsset(source_url="https://example.test/first.mp3", image_url=public_url, status="cached")
    second = AudioAsset(source_url="https://example.test/second.mp3", image_url=public_url, status="cached")
    db.add_all([song, project, first, second])
    db.commit()

    first.song_id = song.id
    first.project_id = project.id
    db.commit()

    result = _delete_cover_content(db, first)

    assert result["shared_reference"] is True
    assert result["removed_files"] == 0
    assert cover_file.exists()
    assert first.image_url is None
    assert second.image_url == public_url
