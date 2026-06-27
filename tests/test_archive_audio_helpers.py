from fastapi import HTTPException
import pytest

from app.models import AudioAsset
from app.routers.archive import (
    _asset_variant_index,
    _extract_uploaded_download_url,
    _get_reusable_audio_url,
    _is_public_http_url,
    _payload_without_empty_values,
    _safe_download_filename,
    _safe_filename_stem,
)


def test_safe_filename_stem_and_payload_cleanup():
    assert _safe_filename_stem(" Donnerbalken 4?! / Mix ", "fallback") == "Donnerbalken_4_Mix"
    assert _payload_without_empty_values({"a": 1, "b": "", "c": None, "d": False}) == {"a": 1, "d": False}


def test_public_url_guard_rejects_private_and_local_urls():
    assert _is_public_http_url("https://cdn.example.test/song.mp3") is True
    assert _is_public_http_url("http://localhost/song.mp3") is False
    assert _is_public_http_url("http://192.168.1.5/song.mp3") is False
    assert _is_public_http_url("file:///tmp/song.mp3") is False


def test_extract_uploaded_download_url_accepts_common_response_shapes():
    assert _extract_uploaded_download_url({"downloadUrl": "https://cdn.example.test/a.mp3"}) == "https://cdn.example.test/a.mp3"
    assert _extract_uploaded_download_url({"data": {"file_url": "https://cdn.example.test/b.mp3"}}) == "https://cdn.example.test/b.mp3"
    assert _extract_uploaded_download_url({"data": "https://cdn.example.test/c.mp3"}) == "https://cdn.example.test/c.mp3"
    assert _extract_uploaded_download_url({"data": {"url": "/media/audio/local.mp3"}}) is None


def test_download_filename_uses_asset_variant_index(isolated_db_session, tmp_path):
    db = isolated_db_session
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"audio")
    first = AudioAsset(project_id=7, title="Donnerbalken 4", display_title="Donnerbalken 4", source_url="https://cdn.example.test/1.mp3", status="remote")
    second = AudioAsset(project_id=7, title="Donnerbalken 4", display_title="Donnerbalken 4", source_url="https://cdn.example.test/2.mp3", status="remote")
    db.add_all([first, second])
    db.commit()

    assert _asset_variant_index(db, first) == 1
    assert _asset_variant_index(db, second) == 2
    assert _safe_download_filename(second, path, db) == "Donnerbalken_4_2.mp3"


def test_get_reusable_audio_url_allows_public_http_only():
    asset = AudioAsset(source_url="https://cdn.example.test/song.mp3", public_url="/media/audio/song.mp3", status="remote")
    assert _get_reusable_audio_url(asset) == "https://cdn.example.test/song.mp3"

    local_only = AudioAsset(source_url="/media/audio/song.mp3", public_url="/media/audio/song.mp3", status="cached")
    with pytest.raises(HTTPException) as exc:
        _get_reusable_audio_url(local_only)
    assert exc.value.status_code == 400
