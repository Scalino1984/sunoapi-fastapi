from pathlib import Path

from app.services.portable_path_service import public_url_for_file, resolve_portable_path, to_portable_path


def test_to_portable_path_returns_storage_relative_path(tmp_path):
    storage = tmp_path / "storage" / "audio"
    storage.mkdir(parents=True)
    audio = storage / "nested" / "song.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"audio")

    assert to_portable_path(audio, storage_root=storage) == "storage/audio/nested/song.mp3"
    assert public_url_for_file(audio, storage_root=storage, public_route="/media/audio") == "/media/audio/nested/song.mp3"


def test_resolve_portable_path_accepts_public_url_filename_and_old_storage_paths(tmp_path):
    storage = tmp_path / "storage" / "audio"
    storage.mkdir(parents=True)
    audio = storage / "song.mp3"
    audio.write_bytes(b"audio")

    assert resolve_portable_path("/media/audio/song.mp3", [storage]) == audio.resolve()
    assert resolve_portable_path("storage/audio/song.mp3", [storage]) == audio.resolve()
    assert resolve_portable_path("song.mp3", [storage]) == audio.resolve()
    assert resolve_portable_path("../secret.mp3", [storage]) is None
