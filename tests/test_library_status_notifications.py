from io import BytesIO

import pytest
from fastapi import UploadFile

from app.models import AudioAsset, StatusNotification
from app.routers.library import create_music_style, delete_music_style, update_library_content_cover, update_music_style
from app.schemas import MusicStyleCreate, MusicStyleUpdate


def test_create_music_style_writes_status_notification(isolated_db_session):
    db = isolated_db_session

    style = create_music_style(MusicStyleCreate(name="Night Drive", style_text="dark synthwave"), db=db)

    notification = db.query(StatusNotification).filter(StatusNotification.event_type == "music_style_created").one()
    assert notification.content_type == "style"
    assert notification.content_id == style.id
    assert notification.target_tab == "styles"
    assert notification.target_payload["style_id"] == style.id
    assert notification.target_payload["status"] == "SUCCESS"


def test_update_and_delete_music_style_write_status_notifications(isolated_db_session):
    db = isolated_db_session
    style = create_music_style(MusicStyleCreate(name="Draft Style", style_text="ambient"), db=db)

    updated = update_music_style(style.id, MusicStyleUpdate(name="Final Style"), db=db)
    deleted = delete_music_style(updated.id, db=db)

    update_notification = (
        db.query(StatusNotification)
        .filter(StatusNotification.event_type == "music_style_updated")
        .one()
    )
    delete_notification = (
        db.query(StatusNotification)
        .filter(StatusNotification.event_type == "music_style_deleted")
        .one()
    )

    assert updated.name == "Final Style"
    assert deleted["deleted_style_id"] == style.id
    assert update_notification.target_tab == "styles"
    assert update_notification.target_payload["style_id"] == style.id
    assert delete_notification.target_tab == "styles"
    assert delete_notification.target_payload["deleted"] is True


@pytest.mark.asyncio
async def test_manual_cover_upload_writes_status_notification_with_library_target(isolated_db_session):
    db = isolated_db_session
    asset = AudioAsset(source_url="manual://cover-upload-test", title="Cover Upload Test", status="remote")
    db.add(asset)
    db.commit()
    db.refresh(asset)

    upload = UploadFile(filename="cover.jpg", file=BytesIO(b"\xff\xd8\xffmanual-cover-upload"))
    upload.headers = {"content-type": "image/jpeg"}

    result = await update_library_content_cover("audio", asset.id, cover=upload, db=db)

    notification = db.query(StatusNotification).filter(StatusNotification.event_type == "library_cover_uploaded").one()
    assert result["cover"]["public_url"].startswith("/media/covers/")
    assert notification.content_type == "audio"
    assert notification.content_id == asset.id
    assert notification.target_tab == "library"
    assert notification.target_payload["audio_asset_id"] == asset.id
    assert notification.target_payload["cover_url"] == result["cover"]["public_url"]
    assert notification.target_payload["status"] == "SUCCESS"
