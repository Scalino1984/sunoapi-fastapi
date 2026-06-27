from types import SimpleNamespace

from app.models import AudioAsset
from app.services import id3_tag_service
from app.services.id3_tag_service import resolve_audio_asset_mp3_path, resolve_cover_image_path


def test_resolve_audio_asset_mp3_path_uses_public_url_and_storage_root(monkeypatch, tmp_path):
    audio_root = tmp_path / "audio"
    cover_root = tmp_path / "covers"
    audio_root.mkdir()
    cover_root.mkdir()
    audio = audio_root / "song.mp3"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(
        id3_tag_service,
        "get_settings",
        lambda: SimpleNamespace(
            audio_storage_path=audio_root,
            suno_audio_public_route="/media/audio",
            cover_storage_path=cover_root,
            suno_cover_public_route="/media/covers",
        ),
    )

    asset = AudioAsset(source_url="https://cdn.example.test/song.mp3", status="cached", public_url="/media/audio/song.mp3")
    assert resolve_audio_asset_mp3_path(asset) == audio.resolve()


def test_resolve_cover_image_path_uses_cache_metadata_and_public_route(monkeypatch, tmp_path):
    audio_root = tmp_path / "audio"
    cover_root = tmp_path / "covers"
    audio_root.mkdir()
    cover_root.mkdir()
    cover = cover_root / "cover.jpg"
    cover.write_bytes(b"cover")
    monkeypatch.setattr(
        id3_tag_service,
        "get_settings",
        lambda: SimpleNamespace(
            audio_storage_path=audio_root,
            suno_audio_public_route="/media/audio",
            cover_storage_path=cover_root,
            suno_cover_public_route="/media/covers",
        ),
    )

    assert resolve_cover_image_path("/media/covers/cover.jpg") == cover.resolve()
    assert resolve_cover_image_path({"filename": "cover.jpg"}) == cover.resolve()
