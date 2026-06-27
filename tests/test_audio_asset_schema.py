from app.models import AudioAsset
from app.schemas import AudioAssetRead


def test_audio_asset_read_marks_cached_asset_as_audio_local():
    asset = AudioAsset(
        id=1,
        source_url="https://cdn.example.test/song.mp3",
        status="cached",
        local_path="storage/audio/song.mp3",
        public_url="/media/audio/song.mp3",
        filename="song.mp3",
    )

    data = AudioAssetRead.model_validate(asset).model_dump()

    assert data["audio_local"] is True
    assert data["audio_availability_status"] == "cached"
    assert data["audio_local_reason"] is None


def test_audio_asset_read_marks_remote_asset_as_not_audio_local():
    asset = AudioAsset(
        id=2,
        source_url="https://cdn.example.test/song.mp3",
        status="remote",
    )

    data = AudioAssetRead.model_validate(asset).model_dump()

    assert data["audio_local"] is False
    assert data["audio_availability_status"] == "remote"
    assert data["audio_local_reason"] == "remote_only"
